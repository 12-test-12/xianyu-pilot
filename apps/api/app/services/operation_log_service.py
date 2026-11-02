"""业务操作日志（operation_log）统一写入服务。

背景：``app/core/audit_middleware.py`` 只记录 HTTP 变更请求，而自动发货发生在
WebSocket 服务内部，不经过 HTTP，因此操作日志页面看不到任何"下单/付款/发货"
的痕迹。本模块提供唯一的业务审计写入入口，供 HTTP 之外的业务代码调用。

约定：
* 调用方负责提交事务（``await db.commit()``）；如需本函数立即提交，传 ``commit=True``。
* 审计写入失败绝不抛出：内部 try/except + ``logger.warning``，不影响主业务流程。
* 兼容 SQLite（桌面版）与 MySQL（服务端）；不引入新依赖。
* 旧库（缺少 status/request_params/response_result/requires_reconciliation/duration_ms
  列）会自动降级为只写旧列，业务描述里保留完整可读信息。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import text

from app.core.logging_security import redact_sensitive, redact_sensitive_text

logger = logging.getLogger(__name__)

# ==================== 业务 operation_type 常量 ====================
ORDER_SYNCED = "ORDER_SYNCED"
ORDER_PAID = "ORDER_PAID"
DELIVERY_STARTED = "DELIVERY_STARTED"
DELIVERY_SUCCEEDED = "DELIVERY_SUCCEEDED"
DELIVERY_FAILED = "DELIVERY_FAILED"
GOODS_SYNCED = "GOODS_SYNCED"
ITEM_PUBLISHED = "ITEM_PUBLISHED"

BUSINESS_OPERATION_TYPES: tuple[str, ...] = (
    ORDER_SYNCED,
    ORDER_PAID,
    DELIVERY_STARTED,
    DELIVERY_SUCCEEDED,
    DELIVERY_FAILED,
    GOODS_SYNCED,
    ITEM_PUBLISHED,
)

# 与前端 LogsPage.vue 的 OPERATION_TYPE_MAP 保持一致
OPERATION_TYPE_LABELS: dict[str, str] = {
    ORDER_SYNCED: "订单同步",
    ORDER_PAID: "订单付款",
    DELIVERY_STARTED: "开始自动发货",
    DELIVERY_SUCCEEDED: "自动发货成功",
    DELIVERY_FAILED: "自动发货失败",
    GOODS_SYNCED: "商品同步",
    ITEM_PUBLISHED: "商品发布",
}

# ==================== 记录状态常量（写入 operation_log.status） ====================
STATUS_COMPLETED = "completed"
STATUS_PENDING = "pending"
STATUS_FAILED = "failed"
STATUS_UNKNOWN = "unknown"
STATUS_REJECTED = "rejected"

STATUS_LABELS: dict[str, str] = {
    STATUS_COMPLETED: "已完成",
    STATUS_PENDING: "进行中",
    STATUS_FAILED: "失败",
    STATUS_UNKNOWN: "结果未知",
    STATUS_REJECTED: "已拒绝",
}

# ==================== 目标类型常量 ====================
TARGET_ORDER = "order"
TARGET_ITEM = "item"
TARGET_DELIVERY = "delivery"
TARGET_GOODS = "goods"

DEFAULT_OPERATOR = "系统"

# 单条文本字段的落库上限，避免把整个响应体写进日志表
MAX_TEXT_LENGTH = 4000
MAX_DESCRIPTION_LENGTH = 1000

# 业务新增列（与迁移 007/046 的顺序一致）
_EXTRA_COLUMNS: tuple[str, ...] = (
    "status",
    "request_params",
    "response_result",
    "requires_reconciliation",
    "duration_ms",
)

_BASE_COLUMNS: tuple[str, ...] = (
    "operator",
    "operation_type",
    "operation_desc",
    "target_type",
    "target_id",
    "ip_address",
    "created_time",
)

_COLUMN_CACHE_KEY = "_operation_log_columns"


def _dialect_name(db: Any) -> str:
    """尽力识别当前会话的数据库方言（sqlite / mysql / ...）。"""
    try:
        bind = getattr(db, "bind", None)
        if bind is None:
            get_bind = getattr(db, "get_bind", None)
            bind = get_bind() if callable(get_bind) else None
        if bind is None:
            return ""
        sync_engine = getattr(bind, "sync_engine", bind)
        dialect = getattr(sync_engine, "dialect", None)
        return str(getattr(dialect, "name", "") or "").lower()
    except Exception:  # pragma: no cover - 纯防御
        return ""


def _json_text(value: Any, *, max_length: int = MAX_TEXT_LENGTH) -> str | None:
    """把任意业务对象序列化为脱敏、截断后的 JSON 文本。"""
    if value is None:
        return None
    if isinstance(value, str):
        raw = value
    else:
        try:
            raw = json.dumps(
                redact_sensitive(value),
                ensure_ascii=False,
                default=str,
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            raw = str(value)
    return redact_sensitive_text(raw, max_length=max_length)


def _short(value: Any, limit: int = 100) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    if not text_value:
        return None
    return text_value[:limit]


def _money(value: Any) -> str:
    if value is None or value == "":
        return "-"
    try:
        return f"¥{float(value):.2f}"
    except (TypeError, ValueError):
        return f"¥{value}"


def _flag(value: bool | int | None) -> int:
    return 1 if value else 0


def _build_payload(
    *,
    operator: str | None,
    operation_type: str,
    description: str,
    target_type: str | None,
    target_id: str | int | None,
    status: str | None,
    request_params: Any,
    response_result: Any,
    requires_reconciliation: bool,
    duration_ms: int | None,
    ip_address: str | None,
) -> dict[str, Any]:
    created_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "operator": _short(operator, 100) or DEFAULT_OPERATOR,
        "operation_type": _short(operation_type, 100) or "OTHER",
        "operation_desc": redact_sensitive_text(
            description or "", max_length=MAX_DESCRIPTION_LENGTH
        ),
        "target_type": _short(target_type, 100),
        "target_id": _short(target_id, 100),
        "ip_address": _short(ip_address, 50),
        "created_time": created_time,
        "status": _short(status, 32) or STATUS_COMPLETED,
        "request_params": _json_text(request_params),
        "response_result": _json_text(response_result),
        "requires_reconciliation": _flag(requires_reconciliation),
        "duration_ms": duration_ms
        if isinstance(duration_ms, int) and duration_ms >= 0
        else None,
    }


async def _existing_columns(db: Any) -> set[str] | None:
    """返回 operation_log 实际存在的列集合；探测失败返回 None（未知）。"""
    try:
        cached = db.info.get(_COLUMN_CACHE_KEY) if hasattr(db, "info") else None
    except Exception:  # pragma: no cover - 纯防御
        cached = None
    if isinstance(cached, set):
        return cached

    dialect = _dialect_name(db)
    columns: set[str] = set()
    try:
        if dialect and dialect != "sqlite":
            result = await db.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = DATABASE() AND table_name = 'operation_log'"
                )
            )
            columns = {str(row[0]).lower() for row in result.fetchall()}
        else:
            try:
                result = await db.execute(text("PRAGMA table_info(operation_log)"))
                columns = {str(row[1]) for row in result.fetchall()}
            except Exception:
                # 方言探测拿不到 engine 时（如 AsyncConnection），退回 MySQL 信息模式
                result = await db.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = DATABASE() AND table_name = 'operation_log'"
                    )
                )
                columns = {str(row[0]).lower() for row in result.fetchall()}
    except Exception as exc:  # 探测失败：不缓存，交给调用方按"未知"处理
        logger.warning(
            "operation log column probe failed dialect=%s errorType=%s",
            dialect,
            type(exc).__name__,
        )
        return None

    if not columns:
        return set()
    if hasattr(db, "info"):
        try:
            db.info[_COLUMN_CACHE_KEY] = columns
        except Exception:  # pragma: no cover - 纯防御
            pass
    return columns


async def existing_columns(db: Any) -> set[str] | None:
    """公开接口：返回 operation_log 实际存在的列集合；None 表示无法探测。

    读取端（``GET /operation-logs``）用它判断是否可以选择业务新增列，
    老库缺列时不会 500。
    """
    return await _existing_columns(db)


def _build_insert_sql(extra_columns: Sequence[str]) -> str:
    columns = list(_BASE_COLUMNS) + list(extra_columns)
    value_exprs = [f":{column}" for column in columns]
    return (
        "INSERT INTO operation_log (\n    "
        + ", ".join(columns)
        + "\n) VALUES (\n    "
        + ", ".join(value_exprs)
        + "\n)"
    )


def _lastrowid(result: Any) -> int | None:
    value = getattr(result, "lastrowid", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def _insert(
    db: Any, payload: dict[str, Any], extra_columns: Sequence[str]
) -> int | None:
    result = await db.execute(text(_build_insert_sql(extra_columns)), payload)
    return _lastrowid(result)


async def _insert_isolated(
    db: Any, payload: dict[str, Any], extra_columns: Sequence[str]
) -> int | None:
    """在 SAVEPOINT 内插入，失败只回滚本条日志，不污染调用方业务事务。"""
    begin_nested = getattr(db, "begin_nested", None)
    if not callable(begin_nested):
        return await _insert(db, payload, extra_columns)
    async with begin_nested():
        return await _insert(db, payload, extra_columns)


async def record_operation(
    db: Any,
    *,
    operation_type: str,
    description: str,
    operator: str | None = None,
    target_type: str | None = None,
    target_id: str | int | None = None,
    status: str = STATUS_COMPLETED,
    request_params: Any = None,
    response_result: Any = None,
    requires_reconciliation: bool = False,
    duration_ms: int | None = None,
    ip_address: str | None = None,
    commit: bool = False,
) -> int | None:
    """写入一条业务操作日志，返回新记录 id；失败返回 None（不抛异常）。

    注意：默认不 commit，由调用方随主业务事务一起提交；若调用方随后 rollback，
    本条日志也会一并回滚（这是期望行为——日志与业务状态保持一致）。
    """
    payload = _build_payload(
        operator=operator,
        operation_type=operation_type,
        description=description,
        target_type=target_type,
        target_id=target_id,
        status=status,
        request_params=request_params,
        response_result=response_result,
        requires_reconciliation=requires_reconciliation,
        duration_ms=duration_ms,
        ip_address=ip_address,
    )

    try:
        columns = await _existing_columns(db)
        if columns is None:
            # 无法探测：先按完整列写，失败再退回旧列
            try:
                record_id = await _insert_isolated(db, payload, _EXTRA_COLUMNS)
            except Exception as exc:
                logger.warning(
                    "operation log full insert failed, retry legacy columns "
                    "type=%s errorType=%s",
                    operation_type,
                    type(exc).__name__,
                )
                record_id = await _insert_isolated(db, payload, ())
        else:
            extra_columns = tuple(
                column for column in _EXTRA_COLUMNS if column in columns
            )
            record_id = await _insert_isolated(db, payload, extra_columns)
    except Exception as exc:
        logger.warning(
            "operation log write skipped type=%s errorType=%s",
            operation_type,
            type(exc).__name__,
        )
        return None

    if commit:
        try:
            await db.commit()
        except Exception as exc:
            logger.warning(
                "operation log commit failed type=%s errorType=%s",
                operation_type,
                type(exc).__name__,
            )
    return record_id


# ==================== 订单类 ====================


async def record_order_synced(
    db: Any,
    *,
    order_id: str | int,
    item_id: str | int | None = None,
    buyer: str | None = None,
    amount: Any = None,
    order_status: str | None = None,
    operator: str | None = None,
    status: str = STATUS_COMPLETED,
    request_params: Any = None,
    response_result: Any = None,
    requires_reconciliation: bool = False,
    duration_ms: int | None = None,
    ip_address: str | None = None,
    commit: bool = False,
) -> int | None:
    description = (
        f"同步订单 {order_id}：商品 {item_id or '-'}，买家 {buyer or '-'}，"
        f"金额 {_money(amount)}，订单状态 {order_status or '-'}"
    )
    return await record_operation(
        db,
        operator=operator,
        operation_type=ORDER_SYNCED,
        description=description,
        target_type=TARGET_ORDER,
        target_id=order_id,
        status=status,
        request_params=request_params,
        response_result=response_result,
        requires_reconciliation=requires_reconciliation,
        duration_ms=duration_ms,
        ip_address=ip_address,
        commit=commit,
    )


async def record_order_paid(
    db: Any,
    *,
    order_id: str | int,
    item_id: str | int | None = None,
    buyer: str | None = None,
    amount: Any = None,
    payment_time: str | None = None,
    operator: str | None = None,
    status: str = STATUS_COMPLETED,
    request_params: Any = None,
    response_result: Any = None,
    requires_reconciliation: bool = False,
    duration_ms: int | None = None,
    ip_address: str | None = None,
    commit: bool = False,
) -> int | None:
    description = (
        f"订单付款 {order_id}：商品 {item_id or '-'}，买家 {buyer or '-'}，"
        f"金额 {_money(amount)}，付款时间 {payment_time or '-'}"
    )
    return await record_operation(
        db,
        operator=operator,
        operation_type=ORDER_PAID,
        description=description,
        target_type=TARGET_ORDER,
        target_id=order_id,
        status=status,
        request_params=request_params,
        response_result=response_result,
        requires_reconciliation=requires_reconciliation,
        duration_ms=duration_ms,
        ip_address=ip_address,
        commit=commit,
    )


# ==================== 自动发货类 ====================


async def record_delivery_started(
    db: Any,
    *,
    order_id: str | int,
    item_id: str | int | None = None,
    buyer: str | None = None,
    amount: Any = None,
    attempt_id: int | None = None,
    delivery_mode: str | None = None,
    operator: str | None = None,
    status: str = STATUS_PENDING,
    request_params: Any = None,
    response_result: Any = None,
    requires_reconciliation: bool = False,
    duration_ms: int | None = None,
    ip_address: str | None = None,
    commit: bool = False,
) -> int | None:
    description = (
        f"开始自动发货：订单 {order_id}，商品 {item_id or '-'}，买家 {buyer or '-'}，"
        f"金额 {_money(amount)}，方式 {delivery_mode or '-'}"
    )
    return await record_operation(
        db,
        operator=operator,
        operation_type=DELIVERY_STARTED,
        description=description,
        target_type=TARGET_DELIVERY,
        target_id=order_id,
        status=status,
        request_params=request_params,
        response_result=response_result,
        requires_reconciliation=requires_reconciliation,
        duration_ms=duration_ms,
        ip_address=ip_address,
        commit=commit,
    )


async def record_delivery_succeeded(
    db: Any,
    *,
    order_id: str | int,
    item_id: str | int | None = None,
    buyer: str | None = None,
    amount: Any = None,
    attempt_id: int | None = None,
    delivery_mode: str | None = None,
    message_confirmed: bool | None = None,
    platform_confirmed: bool | None = None,
    operator: str | None = None,
    request_params: Any = None,
    response_result: Any = None,
    requires_reconciliation: bool | None = None,
    duration_ms: int | None = None,
    ip_address: str | None = None,
    commit: bool = False,
) -> int | None:
    if requires_reconciliation is None:
        requires_reconciliation = platform_confirmed is False
    payload: dict[str, Any] = {
        "orderId": order_id,
        "itemId": item_id,
        "buyer": buyer,
        "amount": amount,
        "attemptId": attempt_id,
        "deliveryMode": delivery_mode,
        "messageConfirmed": message_confirmed,
        "platformConfirmed": platform_confirmed,
    }
    description = (
        f"自动发货成功：订单 {order_id}，商品 {item_id or '-'}，买家 {buyer or '-'}，"
        f"金额 {_money(amount)}，消息确认 {message_confirmed}，平台确认 {platform_confirmed}"
    )
    return await record_operation(
        db,
        operator=operator,
        operation_type=DELIVERY_SUCCEEDED,
        description=description,
        target_type=TARGET_DELIVERY,
        target_id=order_id,
        status=STATUS_COMPLETED,
        request_params=request_params,
        response_result=response_result
        if response_result is not None
        else payload,
        requires_reconciliation=bool(requires_reconciliation),
        duration_ms=duration_ms,
        ip_address=ip_address,
        commit=commit,
    )


async def record_delivery_failed(
    db: Any,
    *,
    order_id: str | int,
    error_code: str | None = None,
    error_message: str | None = None,
    item_id: str | int | None = None,
    buyer: str | None = None,
    attempt_id: int | None = None,
    retry_safe: bool | None = None,
    retry_scope: str | None = None,
    operator: str | None = None,
    request_params: Any = None,
    response_result: Any = None,
    requires_reconciliation: bool = True,
    duration_ms: int | None = None,
    ip_address: str | None = None,
    commit: bool = False,
) -> int | None:
    payload: dict[str, Any] = {
        "orderId": order_id,
        "itemId": item_id,
        "buyer": buyer,
        "attemptId": attempt_id,
        "errorCode": error_code,
        "errorMessage": error_message,
        "retrySafe": retry_safe,
        "retryScope": retry_scope,
    }
    description = (
        f"自动发货失败：订单 {order_id}，商品 {item_id or '-'}，买家 {buyer or '-'}，"
        f"失败原因 {error_code or '-'} / {error_message or '-'}"
    )
    return await record_operation(
        db,
        operator=operator,
        operation_type=DELIVERY_FAILED,
        description=description,
        target_type=TARGET_DELIVERY,
        target_id=order_id,
        status=STATUS_FAILED,
        request_params=request_params,
        response_result=response_result
        if response_result is not None
        else payload,
        requires_reconciliation=requires_reconciliation,
        duration_ms=duration_ms,
        ip_address=ip_address,
        commit=commit,
    )


async def record_delivery_outcome(
    db: Any,
    *,
    order_id: str | int,
    outcome_status: str | None,
    item_id: str | int | None = None,
    buyer: str | None = None,
    amount: Any = None,
    attempt_id: int | None = None,
    delivery_mode: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    message_confirmed: bool | None = None,
    platform_confirmed: bool | None = None,
    retry_safe: bool | None = None,
    retry_scope: str | None = None,
    repeated: bool = False,
    operator: str | None = None,
    request_params: Any = None,
    response_result: Any = None,
    duration_ms: int | None = None,
    ip_address: str | None = None,
    commit: bool = False,
) -> int | None:
    """按 ``RealtimeDeliveryOutcome.status`` 直接落一条业务日志（主 agent 接线用）。

    ``outcome_status`` 取值来自 realtime_delivery.AttemptState（如
    ``succeeded`` / ``failed`` / ``unknown`` / ``message_sent`` / ``in_progress``），
    本函数按关键字归类为 DELIVERY_SUCCEEDED / DELIVERY_FAILED / DELIVERY_STARTED，
    未知取值按"已开始但结果待核对"记录（宁可多记不可漏记）。
    """
    normalized = str(outcome_status or "").strip().lower()
    if normalized in {"succeeded", "success", "delivered", "completed", "done"}:
        return await record_delivery_succeeded(
            db,
            order_id=order_id,
            item_id=item_id,
            buyer=buyer,
            amount=amount,
            attempt_id=attempt_id,
            delivery_mode=delivery_mode,
            message_confirmed=message_confirmed,
            platform_confirmed=platform_confirmed,
            operator=operator,
            request_params=request_params,
            response_result=response_result,
            duration_ms=duration_ms,
            ip_address=ip_address,
            commit=commit,
        )
    if normalized in {"failed", "error"}:
        return await record_delivery_failed(
            db,
            order_id=order_id,
            error_code=error_code,
            error_message=error_message,
            item_id=item_id,
            buyer=buyer,
            attempt_id=attempt_id,
            retry_safe=retry_safe,
            retry_scope=retry_scope,
            operator=operator,
            request_params=request_params,
            response_result=response_result,
            requires_reconciliation=True,
            duration_ms=duration_ms,
            ip_address=ip_address,
            commit=commit,
        )
    # unknown / message_sent / in_progress / 其他：已开始但结果待核对
    extra_result: dict[str, Any] = (
        dict(response_result) if isinstance(response_result, dict) else {}
    )
    extra_result.setdefault("outcomeStatus", normalized or None)
    extra_result.setdefault("attemptId", attempt_id)
    extra_result.setdefault("messageConfirmed", message_confirmed)
    extra_result.setdefault("platformConfirmed", platform_confirmed)
    extra_result.setdefault("errorCode", error_code)
    extra_result.setdefault("errorMessage", error_message)
    extra_result.setdefault("repeated", repeated)
    return await record_delivery_started(
        db,
        order_id=order_id,
        item_id=item_id,
        buyer=buyer,
        amount=amount,
        attempt_id=attempt_id,
        delivery_mode=delivery_mode,
        operator=operator,
        status=STATUS_UNKNOWN
        if normalized in {"unknown", "message_sent"}
        else STATUS_PENDING,
        request_params=request_params,
        response_result=extra_result or None,
        requires_reconciliation=True,
        duration_ms=duration_ms,
        ip_address=ip_address,
        commit=commit,
    )


# ==================== 商品类 ====================


async def record_goods_synced(
    db: Any,
    *,
    account_id: str | int | None = None,
    goods_count: int | None = None,
    item_ids: Sequence[str | int] | None = None,
    operator: str | None = None,
    status: str = STATUS_COMPLETED,
    request_params: Any = None,
    response_result: Any = None,
    requires_reconciliation: bool = False,
    duration_ms: int | None = None,
    ip_address: str | None = None,
    commit: bool = False,
) -> int | None:
    sample_ids = ", ".join(str(item) for item in list(item_ids or [])[:5]) or "-"
    description = (
        f"同步商品：账号 {account_id or '-'}，"
        f"共 {goods_count if goods_count is not None else '-'} 件，商品ID {sample_ids}"
    )
    return await record_operation(
        db,
        operator=operator,
        operation_type=GOODS_SYNCED,
        description=description,
        target_type=TARGET_GOODS,
        target_id=account_id,
        status=status,
        request_params=request_params,
        response_result=response_result,
        requires_reconciliation=requires_reconciliation,
        duration_ms=duration_ms,
        ip_address=ip_address,
        commit=commit,
    )


async def record_item_published(
    db: Any,
    *,
    item_id: str | int,
    title: str | None = None,
    price: Any = None,
    operator: str | None = None,
    status: str = STATUS_COMPLETED,
    error_message: str | None = None,
    request_params: Any = None,
    response_result: Any = None,
    requires_reconciliation: bool | None = None,
    duration_ms: int | None = None,
    ip_address: str | None = None,
    commit: bool = False,
) -> int | None:
    if requires_reconciliation is None:
        requires_reconciliation = status in {STATUS_FAILED, STATUS_UNKNOWN}
    description = (
        f"发布商品 {item_id}：标题 {title or '-'}，价格 {_money(price)}"
        + (f"，失败原因 {error_message}" if error_message else "")
    )
    return await record_operation(
        db,
        operator=operator,
        operation_type=ITEM_PUBLISHED,
        description=description,
        target_type=TARGET_ITEM,
        target_id=item_id,
        status=status,
        request_params=request_params,
        response_result=response_result,
        requires_reconciliation=bool(requires_reconciliation),
        duration_ms=duration_ms,
        ip_address=ip_address,
        commit=commit,
    )
