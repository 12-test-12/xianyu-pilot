"""
闲鱼网页版扫码登录模块（Playwright 浏览器会话）。

二维码生成、扫码状态、换票采集全部由 qr_login_browser.QrLoginWorker 在
同一浏览器上下文里完成：requests 无法执行 login_token/login.do 返回的 HTML/JS，
Cookie 里始终拿不到 unb，因此不再走 HTTP 换票（参照 ai-goofish-monitor）。

本模块保留原有的会话注册表语义：owner 归属、容量上限、TTL、终止态回放、
持久化回执；对外 API（generate_qrcode / get_session_status /
get_session_cookies / mark_session_persisted / cleanup_*）与路由层约定不变。
"""

import hashlib
import logging
import secrets
import threading
import time
from typing import Optional

from .qr_login_browser import (
    QR_READY_TIMEOUT,
    QrLoginUnavailableError,
    QrLoginWorker,
)

logger = logging.getLogger(__name__)

# ==================== 常量 ====================

SESSION_TIMEOUT = 300  # 5 分钟
# 每个活跃会话占一个 Chromium 实例，上限远低于纯 HTTP 会话的 32。
MAX_ACTIVE_SESSIONS = 8


class QrSessionCapacityError(RuntimeError):
    """Raised when every bounded QR session slot is still active."""


# ==================== 会话管理 ====================

_sessions: dict[str, dict] = {}
_lock = threading.Lock()
desktop_worker_factory = None  # 由原生宿主注册；无 Qt 的服务端继续使用 Playwright。


def _session_operation_lock(session_data: dict) -> threading.Lock:
    # ``setdefault`` gives manually restored/test sessions the same single
    # lock even when two worker threads first touch them concurrently.
    return session_data.setdefault("operation_lock", threading.RLock())


def _close_session_data(session_data: dict, *, log_message: str) -> None:
    """Close one detached session after any in-flight operation completes."""

    operation_lock = _session_operation_lock(session_data)
    with operation_lock:
        worker = session_data.get("worker")
        if worker is not None:
            try:
                worker.cancel()
                worker.join(timeout=1)
            except Exception as exc:
                logger.debug("%s errorType=%s", log_message, type(exc).__name__)


def _is_terminal_session(session_data: dict) -> bool:
    return str(session_data.get("status") or "").casefold() in {
        "confirmed",
        "expired",
        "cancelled",
        "failed",
    }


def _preflight_session_capacity(normalized_owner: str) -> None:
    """Reject an obviously full registry before starting a browser.

    This is deliberately only a fast preflight. ``generate_qrcode`` repeats
    the admission decision atomically after the QR screenshot because
    another request may consume the last slot in the meantime.
    """

    with _lock:
        owner_can_replace = bool(normalized_owner) and any(
            str(session_data.get("owner_key") or "").strip().casefold()
            == normalized_owner
            for session_data in _sessions.values()
        )
        terminal_can_be_evicted = any(
            _is_terminal_session(session_data)
            for session_data in _sessions.values()
        )
        if (
            len(_sessions) >= MAX_ACTIVE_SESSIONS
            and not owner_can_replace
            and not terminal_can_be_evicted
        ):
            raise QrSessionCapacityError(
                "扫码登录会话已达容量上限，请稍后重试"
            )


def _cleanup_expired():
    """清理过期会话。"""
    return cleanup_expired_sessions()


def cleanup_expired_sessions() -> int:
    """Remove only expired QR sessions and cancel their browsers."""
    now = time.time()
    with _lock:
        expired = [
            _sessions.pop(sid)
            for sid, session_data in list(_sessions.items())
            if now - float(session_data.get("created_at") or 0) > SESSION_TIMEOUT
        ]
    for session_data in expired:
        _close_session_data(
            session_data,
            log_message="关闭过期扫码会话失败",
        )
    return len(expired)


# ==================== Worker 状态同步 ====================


def _create_worker(*, timeout: int) -> QrLoginWorker:
    """工厂钩子：测试用假 worker 替换真实浏览器会话。"""
    factory = desktop_worker_factory or QrLoginWorker
    return factory(timeout=timeout)


def _sync_worker_state(session_data: dict) -> None:
    """把浏览器 worker 的最新快照推进到会话记录。

    须持有会话 operation_lock 调用。worker 只在自己线程里前进状态，
    终止态（confirmed/expired/cancelled/failed）一旦写入即不可再变。
    """

    worker = session_data.get("worker")
    if worker is None:
        return
    snap = worker.snapshot()
    status = str(snap.get("status") or "").casefold()
    if status in ("", "starting"):
        return
    if status in ("new", "scaned", "verification_required"):
        if snap.get("qr_image"):
            session_data["qr_image"] = snap["qr_image"]
        session_data["status"] = status
        session_data["message"] = snap.get("message")
        return
    if status == "confirmed":
        cookies = dict(snap.get("cookies") or {})
        unb = str(cookies.get("unb") or "").strip()
        if not unb:
            # 防御：判定成功却拿不到 unb 时不落终止态，等 worker 超时兜底。
            return
        session_data["saved_cookies"] = cookies
        session_data["status"] = "confirmed"
        session_data["terminal_result"] = {
            "status": "confirmed",
            "unb": unb,
            "externalUid": unb,
        }
        return
    if status in ("expired", "cancelled", "failed"):
        result = {"status": status}
        if snap.get("error"):
            result["message"] = str(snap["error"])
        session_data["status"] = status
        session_data["terminal_result"] = result


def _replay_terminal(session_data: dict) -> dict:
    """回放不可变的终止态与持久化回执，让丢失响应的客户端可安全重试。"""

    replay = dict(session_data.get("terminal_result") or {})
    persistence_result = session_data.get("persistence_result")
    if isinstance(persistence_result, dict):
        replay.update(persistence_result)
    return replay


# ==================== 公开 API ====================


def generate_qrcode(
    user_id: int = None,
    tenant_id: int = None,
    *,
    owner_key: str | None = None,
    target_account_id: int | None = None,
) -> dict:
    """
    创建新的扫码登录会话，启动浏览器并等待二维码截图就绪。
    user_id/tenant_id: 当前登录用户的上下文，扫码成功后用于归属账号。
    target_account_id: 若是重新扫码，指定需要更新凭据的目标账号ID。
    返回: {"sessionId": str, "qrImage": str (base64 data URI)}
    """
    normalized_owner = str(owner_key or "").strip().casefold()
    cleanup_expired_sessions()
    _preflight_session_capacity(normalized_owner)

    session_id = secrets.token_urlsafe(24)
    worker = _create_worker(timeout=SESSION_TIMEOUT)
    created_at = time.time()
    session_data = {
        "worker": worker,
        "qr_image": None,
        "status": "starting",
        "created_at": created_at,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "target_account_id": target_account_id,
        "owner_key": normalized_owner,
        "operation_lock": threading.RLock(),
    }

    # Reserve capacity before launching Chromium. Slow startup must count
    # against the limit too; no browser work holds the registry lock.
    cleanup_expired_sessions()
    detached: list[dict] = []
    at_capacity = False
    with _lock:
        if normalized_owner:
            for existing_id, existing_data in list(_sessions.items()):
                if (
                    str(existing_data.get("owner_key") or "").strip().casefold()
                    == normalized_owner
                ):
                    detached.append(_sessions.pop(existing_id))

        while len(_sessions) >= MAX_ACTIVE_SESSIONS:
            terminal = [
                (existing_id, existing_data)
                for existing_id, existing_data in _sessions.items()
                if _is_terminal_session(existing_data)
            ]
            if not terminal:
                at_capacity = True
                break
            evicted_id, _ = min(
                terminal,
                key=lambda item: float(item[1].get("created_at") or 0),
            )
            detached.append(_sessions.pop(evicted_id))

        if not at_capacity:
            _sessions[session_id] = session_data

    for old_session_data in detached:
        _close_session_data(
            old_session_data,
            log_message="关闭被替换或回收的扫码会话失败",
        )
    if at_capacity:
        _close_session_data(
            session_data,
            log_message="关闭超出容量的扫码会话失败",
        )
        raise QrSessionCapacityError("扫码登录会话已达容量上限，请稍后重试")

    try:
        worker.start()
        qr_image = worker.wait_qr_ready(QR_READY_TIMEOUT)
        with _session_operation_lock(session_data):
            with _lock:
                if _sessions.get(session_id) is not session_data:
                    raise QrLoginUnavailableError("扫码会话已取消，请重新生成二维码。")
                session_data["qr_image"] = qr_image
                session_data["status"] = "new"
    except Exception as exc:
        cleanup_session(session_id)
        if isinstance(exc, QrLoginUnavailableError):
            raise
        logger.error("生成二维码失败 errorType=%s", type(exc).__name__)
        raise QrLoginUnavailableError("生成闲鱼登录二维码失败，请稍后重试。") from exc

    logger.info(
        "闲鱼扫码登录会话已创建 sessionHash=%s userId=%s tenantId=%s",
        hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12],
        user_id,
        tenant_id,
    )
    return {"sessionId": session_id, "qrImage": qr_image}


def get_session_status(session_id: str) -> dict:
    """
    获取会话状态：读取浏览器 worker 快照，不发起任何网络请求。
    确认登录成功后不再返回原始 Cookie，仅返回安全的摘要信息。
    verification_required 为等待用户完成验证的活跃状态，完成后继续采集凭据。
    """
    _cleanup_expired()

    with _lock:
        sdata = _sessions.get(session_id)
    if not sdata:
        return {"status": "expired", "message": "会话不存在或已过期"}

    operation_lock = _session_operation_lock(sdata)
    with operation_lock:
        with _lock:
            if _sessions.get(session_id) is not sdata:
                return {"status": "expired", "message": "会话不存在或已过期"}
            if time.time() - float(sdata.get("created_at") or 0) > SESSION_TIMEOUT:
                _sessions.pop(session_id, None)
                close_expired = True
            else:
                close_expired = False

        if close_expired:
            _close_session_data(sdata, log_message="关闭超时扫码会话失败")
            return {"status": "expired", "message": "登录超时"}

        # QR confirmation is one-shot. Replaying the immutable terminal result
        # lets clients safely retry after a lost response.
        if _is_terminal_session(sdata) and isinstance(sdata.get("terminal_result"), dict):
            return _replay_terminal(sdata)

        _sync_worker_state(sdata)
        if _is_terminal_session(sdata) and isinstance(sdata.get("terminal_result"), dict):
            return _replay_terminal(sdata)

        result = {"status": str(sdata.get("status") or "new")}
        if sdata.get("message"):
            result["message"] = sdata["message"]
        persistence_result = sdata.get("persistence_result")
        if isinstance(persistence_result, dict):
            result.update(persistence_result)
        return result


def get_session_cookies(session_id: str) -> Optional[dict]:
    """
    内部使用：获取登录成功后的完整 Cookie 数据和用户上下文。
    仅在 worker 采集到已登录 Cookie 后返回有效数据。
    返回: {"cookies": dict, "user_id": int, "tenant_id": int, "cookie_text": str, "unb": str, "m_h5_tk": str}
    """
    with _lock:
        sdata = _sessions.get(session_id)
    if not sdata:
        return None
    operation_lock = _session_operation_lock(sdata)
    with operation_lock:
        with _lock:
            if _sessions.get(session_id) is not sdata:
                return None
            expired = (
                time.time() - float(sdata.get("created_at") or 0)
                > SESSION_TIMEOUT
            )
            if expired:
                _sessions.pop(session_id, None)

        if expired:
            _close_session_data(sdata, log_message="关闭超时扫码会话失败")
            return None

        saved_cookies = sdata.get("saved_cookies")
        if not saved_cookies:
            # 状态轮询可能还没跑过；让 worker 快照先把 confirmed 落进来。
            _sync_worker_state(sdata)
            saved_cookies = sdata.get("saved_cookies")
        if not saved_cookies:
            return None

        cookies = dict(saved_cookies)
        return {
            "cookies": cookies,
            "cookie_text": _format_cookies(cookies),
            "unb": cookies.get("unb", ""),
            "m_h5_tk": cookies.get("_m_h5_tk", ""),
            "user_id": sdata.get("user_id"),
            "tenant_id": sdata.get("tenant_id"),
            "target_account_id": sdata.get("target_account_id"),
        }


def mark_session_persisted(session_id: str, result: dict) -> bool:
    """Attach a safe persistence receipt for idempotent status retries."""

    with _lock:
        sdata = _sessions.get(session_id)
    if not sdata:
        return False

    operation_lock = _session_operation_lock(sdata)
    with operation_lock:
        with _lock:
            if _sessions.get(session_id) is not sdata:
                return False
            if sdata.get("status") != "confirmed" or not sdata.get("saved_cookies"):
                return False
            sdata["persistence_result"] = {
                key: result[key]
                for key in (
                    "accountId",
                    "cookieStatus",
                    "expireTime",
                    "message",
                    "persisted",
                )
                if key in result
            }
    return True


def get_session_context(session_id: str) -> Optional[dict]:
    """获取会话的用户上下文，不执行轮询。"""
    with _lock:
        sdata = _sessions.get(session_id)
    if not sdata:
        return None
    if time.time() - float(sdata.get("created_at") or 0) > SESSION_TIMEOUT:
        cleanup_session(session_id)
        return None
    return {
        "user_id": sdata.get("user_id"),
        "tenant_id": sdata.get("tenant_id"),
        "owner_key": sdata.get("owner_key"),
        "status": sdata.get("status"),
    }


def cleanup_session(session_id: str):
    """清理指定会话。"""
    with _lock:
        session_data = _sessions.pop(session_id, None)
    if session_data:
        _close_session_data(session_data, log_message="关闭扫码会话失败")


def cleanup_owner_sessions(owner_key: str) -> int:
    """Close only QR sessions created by the authenticated owner."""

    normalized_owner = str(owner_key or "").strip().casefold()
    if not normalized_owner:
        return 0
    with _lock:
        owned = [
            _sessions.pop(session_id)
            for session_id, session_data in list(_sessions.items())
            if str(session_data.get("owner_key") or "").strip().casefold()
            == normalized_owner
        ]
    for session_data in owned:
        _close_session_data(
            session_data,
            log_message="关闭当前用户扫码会话失败",
        )
    return len(owned)


def cleanup_all():
    """清理所有会话。"""
    with _lock:
        sessions = list(_sessions.values())
        _sessions.clear()
    for session_data in sessions:
        _close_session_data(session_data, log_message="关闭扫码会话失败")


# ==================== Cookie 工具函数 ====================


def _format_cookies(cookies: dict) -> str:
    """
    将 dict 格式的 Cookie 合并为完整的 Cookie 字符串。
    格式: "key1=value1; key2=value2; ..."
    """
    if not cookies:
        return ""
    return "; ".join(f"{k}={v}" for k, v in cookies.items())
