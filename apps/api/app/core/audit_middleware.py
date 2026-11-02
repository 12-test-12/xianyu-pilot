"""Durable, fail-closed audit intents for authenticated API mutations."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
from typing import Any, Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from .database import async_session
from .logging_security import redact_sensitive, redact_sensitive_text
from .response import ResultObject
from .security import request_client_ip

logger = logging.getLogger(__name__)
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_SENSITIVE_PATH_SEGMENTS = (
    re.compile(r"(?i)(/(?:internal/)?qrlogin/(?:status|cookies)/)[^/]+"),
    re.compile(r"(?i)(/ads/payment/orders/)[^/]+"),
)

# 请求体审计上限：超过该长度或为二进制/表单上传时只记录元信息，避免把文件
# 内容写进日志表。
_MAX_AUDIT_BODY_BYTES = 8192
_MAX_AUDIT_TEXT = 4000
_MAX_AUDIT_DESCRIPTION = 1000
_AUDITABLE_CONTENT_TYPES = ("json", "x-www-form-urlencoded", "text/plain")

# 业务可读动作名：命中则拼在描述前面，让"操作日志"不再只有 HTTP 语义。
_PATH_ACTION_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)^/api/order/confirmShipment"), "确认发货"),
    (re.compile(r"(?i)^/api/order/"), "订单操作"),
    (re.compile(r"(?i)^/api/(?:items?|goods)/"), "商品操作"),
    (re.compile(r"(?i)^/api/delivery"), "自动发货配置"),
    (re.compile(r"(?i)^/api/(?:auth|login|logout|profile)"), "账号操作"),
    (re.compile(r"(?i)^/api/system"), "系统设置"),
    (re.compile(r"(?i)^/api/notification"), "通知配置"),
)

# 记录状态（写入 operation_log.status，与 operation_log_service 常量保持一致）
_STATUS_COMPLETED = "completed"
_STATUS_PENDING = "pending"
_STATUS_FAILED = "failed"
_STATUS_UNKNOWN = "unknown"
_STATUS_REJECTED = "rejected"

_STATUS_TEXT = {
    _STATUS_COMPLETED: "已完成",
    _STATUS_PENDING: "进行中",
    _STATUS_FAILED: "失败",
    _STATUS_UNKNOWN: "结果未知",
    _STATUS_REJECTED: "已拒绝",
}

# operation_log 业务新增列（桌面迁移 007 / 服务端迁移 046）
_EXTRA_COLUMNS = (
    "status",
    "request_params",
    "response_result",
    "requires_reconciliation",
    "duration_ms",
)

_FULL_INSERT_SQL = """
INSERT INTO operation_log(
    operator, operation_type, operation_desc, target_type,
    target_id, ip_address, created_time,
    status, request_params, requires_reconciliation
) VALUES(
    :operator, :operation_type, :description, 'api_mutation',
    :request_id, :ip_address, NOW(),
    :status, :request_params, :requires_reconciliation
)
"""

_LEGACY_INSERT_SQL = """
INSERT INTO operation_log(
    operator, operation_type, operation_desc, target_type,
    target_id, ip_address, created_time
) VALUES(
    :operator, :operation_type, :description, 'api_mutation',
    :request_id, :ip_address, NOW()
)
"""

_FULL_UPDATE_SQL = """
UPDATE operation_log
SET operation_type = :operation_type,
    operation_desc = :description,
    status = :status,
    response_result = :response_result,
    requires_reconciliation = :requires_reconciliation,
    duration_ms = :duration_ms
WHERE id = :audit_id
"""

_LEGACY_UPDATE_SQL = """
UPDATE operation_log
SET operation_type = :operation_type,
    operation_desc = :description
WHERE id = :audit_id
"""


def _client_hash(request: Request) -> str:
    # Resolve proxy headers only when the immediate peer is trusted, then use a
    # keyed digest so a leaked audit export cannot be used as a cheap IPv4
    # dictionary. The domain prefix prevents cross-protocol use of the JWT key.
    source = request_client_ip(request)
    digest = hmac.new(
        str(settings.jwt_secret).encode("utf-8"),
        f"audit-client\0{source}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"hmac-sha256:{digest[:24]}"


def _audit_outcome(status_code: int) -> tuple[str, str]:
    """Return an honest operation type and description state for one response."""

    if 200 <= status_code < 300:
        return "HTTP_MUTATION_COMPLETED", "completed"
    if 400 <= status_code < 500:
        return "HTTP_MUTATION_REJECTED", "rejected"
    # Redirects are not proof that the intended handler ran, and 5xx responses
    # may follow an irreversible side effect. Both require reconciliation.
    return "HTTP_MUTATION_RESULT_UNKNOWN", "result_unknown"


def _outcome_status(outcome: str) -> tuple[str, int]:
    """Map the outcome keyword to (status column value, requires_reconciliation)."""

    if outcome == "completed":
        return _STATUS_COMPLETED, 0
    if outcome == "rejected":
        return _STATUS_REJECTED, 0
    if outcome == "started":
        return _STATUS_PENDING, 1
    return _STATUS_UNKNOWN, 1


def _audit_path(path: str) -> str:
    """Remove bearer-like or payment identifiers embedded in known API paths."""

    sanitized = str(path or "")
    for pattern in _SENSITIVE_PATH_SEGMENTS:
        sanitized = pattern.sub(r"\1<redacted>", sanitized)
    return sanitized[:1000]


def _path_action_hint(path: str) -> str | None:
    for pattern, label in _PATH_ACTION_HINTS:
        if pattern.search(path or ""):
            return label
    return None


def _audit_description(
    request: Request,
    status: str,
    http_status: int | None = None,
) -> str:
    """人类可读的中文业务描述（不再是裸 JSON），保留 requestId 便于核对。

    例：``订单操作：调用接口 POST /api/order/confirmShipment（成功），requestId=...``
    """

    path = _audit_path(request.url.path)
    status_text = _STATUS_TEXT.get(_outcome_status(status)[0], status)
    hint = _path_action_hint(path)
    prefix = f"{hint}：" if hint else ""
    parts = [f"{prefix}调用接口 {request.method} {path}（{status_text}）"]
    if http_status is not None:
        parts.append(f"HTTP {int(http_status)}")
    request_id = str(getattr(request.state, "request_id", ""))[:100]
    if request_id:
        parts.append(f"requestId={request_id}")
    description = "，".join(parts)
    return redact_sensitive_text(description, max_length=_MAX_AUDIT_DESCRIPTION)


async def _audit_request_params(request: Request) -> str | None:
    """采集脱敏后的请求体；二进制/超大请求体只记录元信息，绝不阻塞主请求。"""

    content_type = str(request.headers.get("content-type") or "").lower()
    if content_type and not any(
        token in content_type for token in _AUDITABLE_CONTENT_TYPES
    ):
        return json.dumps(
            {"contentType": content_type[:120], "bodyOmitted": True},
            ensure_ascii=False,
            separators=(",", ":"),
        )

    try:
        content_length = int(request.headers.get("content-length") or 0)
    except (TypeError, ValueError):
        content_length = 0
    if content_length > _MAX_AUDIT_BODY_BYTES:
        return json.dumps(
            {"bodyOmitted": True, "contentLength": content_length},
            ensure_ascii=False,
            separators=(",", ":"),
        )

    try:
        raw = await request.body()
    except Exception as exc:  # noqa: BLE001 - 审计采集失败不得影响业务
        logger.warning(
            "mutation audit body unavailable request_id=%s errorType=%s",
            getattr(request.state, "request_id", ""),
            type(exc).__name__,
        )
        return None
    if not raw:
        return None

    text_value = raw.decode("utf-8", "replace")
    parsed: Any = None
    if "json" in content_type:
        try:
            parsed = json.loads(text_value)
        except (TypeError, ValueError):
            parsed = None
    if parsed is not None:
        text_value = json.dumps(
            redact_sensitive(parsed),
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )
    else:
        text_value = redact_sensitive_text(text_value)
    return text_value[:_MAX_AUDIT_TEXT]


def _request_params_placeholder(request: Request) -> str | None:
    """无请求体时记录查询参数，便于追溯（GET 不审计，但 PUT/PATCH 可能用 query）。"""

    try:
        query = request.url.query
    except Exception:  # noqa: BLE001 - 纯防御
        return None
    if not query:
        return None
    return redact_sensitive_text(query, max_length=_MAX_AUDIT_TEXT)


async def _create_audit_intent(request: Request) -> int:
    user = getattr(request.state, "current_user", None) or {}
    operator = str(user.get("username") or "authenticated-admin")[:64]
    request_id = str(getattr(request.state, "request_id", ""))[:100]
    status, requires_reconciliation = _outcome_status("started")
    request_params = await _audit_request_params(request)
    if request_params is None:
        request_params = _request_params_placeholder(request)

    params = {
        "operator": operator,
        "operation_type": "HTTP_MUTATION_STARTED",
        "description": _audit_description(request, "started"),
        "request_id": request_id,
        "ip_address": _client_hash(request),
        "status": status,
        "request_params": request_params,
        "requires_reconciliation": requires_reconciliation,
    }
    async with async_session() as db:
        try:
            result = await db.execute(text(_FULL_INSERT_SQL), params)
        except Exception as exc:  # noqa: BLE001 - 旧库缺列时退回旧列写入
            logger.warning(
                "mutation audit full insert unavailable, retry legacy columns "
                "request_id=%s errorType=%s",
                request_id,
                type(exc).__name__,
            )
            await db.rollback()
            result = await db.execute(text(_LEGACY_INSERT_SQL), params)
        await db.commit()
        return int(result.lastrowid)


async def _finish_audit_intent(
    request: Request,
    audit_id: int,
    status_code: int,
    *,
    duration_ms: int | None = None,
    response_result: str | None = None,
) -> None:
    operation_type, outcome = _audit_outcome(status_code)
    status, requires_reconciliation = _outcome_status(outcome)
    params = {
        "audit_id": audit_id,
        "operation_type": operation_type,
        "description": _audit_description(request, outcome, status_code),
        "status": status,
        "response_result": response_result,
        "requires_reconciliation": requires_reconciliation,
        "duration_ms": duration_ms,
    }
    async with async_session() as db:
        try:
            result = await db.execute(text(_FULL_UPDATE_SQL), params)
        except Exception as exc:  # noqa: BLE001 - 旧库缺列时退回旧列更新
            logger.warning(
                "mutation audit full update unavailable, retry legacy columns "
                "audit_id=%s errorType=%s",
                audit_id,
                type(exc).__name__,
            )
            await db.rollback()
            result = await db.execute(text(_LEGACY_UPDATE_SQL), params)
        if int(result.rowcount or 0) != 1:
            raise RuntimeError("mutation audit intent disappeared before completion")
        await db.commit()


def _unavailable(request: Request) -> JSONResponse:
    request_id = str(getattr(request.state, "request_id", ""))
    payload = ResultObject.failed(
        "审计存储暂不可用，写操作未执行",
        code=503,
    ).model_dump(by_alias=True)
    payload["requestId"] = request_id
    return JSONResponse(
        status_code=503,
        content=payload,
        headers={"X-Request-ID": request_id},
    )


class MutationAuditMiddleware(BaseHTTPMiddleware):
    """Persist an intent before every authenticated mutation.

    A completion update is best-effort because the durable ``STARTED`` row is
    already sufficient to flag a crash window as requiring reconciliation.
    The business handler never runs if the initial audit insert cannot commit.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        should_audit = (
            settings.audit_mutation_intent_required
            and request.method.upper() in _MUTATING_METHODS
            and request.url.path.startswith("/api/")
            # These authenticated compatibility paths are retired lookups that
            # always return 410 and can no longer mutate state. Writing an
            # audit intent for them would create a misleading mutation record.
            and not request.url.path.startswith("/api/internal/qrlogin/")
            and getattr(request.state, "current_user", None) is not None
        )
        if not should_audit:
            return await call_next(request)

        started_at = time.perf_counter()
        try:
            audit_id = await _create_audit_intent(request)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "mutation audit intent unavailable request_id=%s errorType=%s",
                getattr(request.state, "request_id", ""),
                type(exc).__name__,
            )
            return _unavailable(request)

        def _elapsed_ms() -> int:
            return max(0, int((time.perf_counter() - started_at) * 1000))

        try:
            response = await call_next(request)
        except BaseException:
            try:
                await _finish_audit_intent(
                    request,
                    audit_id,
                    status_code=500,
                    duration_ms=_elapsed_ms(),
                    response_result=json.dumps(
                        {"errorType": "unhandled_exception"},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "mutation audit completion unavailable audit_id=%s errorType=%s",
                    audit_id,
                    type(exc).__name__,
                )
            raise

        try:
            await _finish_audit_intent(
                request,
                audit_id,
                response.status_code,
                duration_ms=_elapsed_ms(),
                response_result=json.dumps(
                    {"httpStatus": int(response.status_code)},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "mutation audit completion unavailable audit_id=%s errorType=%s",
                audit_id,
                type(exc).__name__,
            )
        return response
