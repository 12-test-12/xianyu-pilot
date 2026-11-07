import asyncio
from unittest.mock import AsyncMock

import pytest

from app.services import ws_token


@pytest.mark.asyncio
async def test_expired_ws_waits_for_rescan_then_uses_new_cookie(monkeypatch):
    from app.services import cookie_token_refresher, notify_dispatcher, ws_client

    client = ws_client.XianyuWebSocketClient(11, "old-cookie", "old-token", "user-11")
    alert_sent = asyncio.Event()
    connected = asyncio.Event()
    attempts = []

    def token_api(cookie, token):
        attempts.append((cookie, token))
        if cookie == "old-cookie":
            return None, None, "expired", None
        return "access-token", token, None, None

    async def connect():
        if await client._refresh_token():
            connected.set()

    save_status = AsyncMock(return_value=True)
    notify = AsyncMock(side_effect=lambda *args: alert_sent.set())
    monkeypatch.setattr(ws_client, "get_ws_token_with_refreshed_m_h5_tk", token_api)
    monkeypatch.setattr(cookie_token_refresher, "_update_cookie_status", save_status)
    monkeypatch.setattr(notify_dispatcher, "notify_cookie_expired", notify)
    monkeypatch.setattr(ws_client.broadcaster, "broadcast", AsyncMock())
    monkeypatch.setattr(client, "_connect", connect)
    monkeypatch.setattr(ws_client, "RECONNECT_DELAY", 0.01)

    await client.start()
    try:
        await asyncio.wait_for(alert_sent.wait(), timeout=2)
        await asyncio.sleep(0.04)
        assert attempts == [("old-cookie", "old-token")]
        assert client.phase == "cookie_expired"
        client.update_credentials("new-cookie", "new-token")
        await asyncio.wait_for(connected.wait(), timeout=2)
        assert attempts[-1] == ("new-cookie", "new-token")
        assert save_status.await_args.kwargs["expected_cookie"] == "old-cookie"
        notify.assert_awaited_once()
    finally:
        await client.stop()


@pytest.mark.parametrize(("response", "status", "refreshes"), [
    (None, "unavailable", True),
    (ws_token.CAPTCHA_NEEDED, "captcha", True),
    (ws_token.SESSION_EXPIRED, "expired", True),
])
def test_ws_token_failure_classification(monkeypatch, response, status, refreshes):
    attempts = []
    refresh_attempts = []

    def token_api(cookie, token):
        attempts.append(token)
        return response

    def refresh(cookie):
        refresh_attempts.append(cookie)
        return None, None

    monkeypatch.setattr(ws_token, "_call_token_api", token_api)
    monkeypatch.setattr(ws_token, "refresh_m_h5_tk", refresh)
    result = ws_token.get_ws_token_with_refreshed_m_h5_tk("_m_h5_tk=test", "test")
    assert result == (None, None, status, None)
    assert attempts == ["test"]
    assert bool(refresh_attempts) is refreshes


def test_ws_token_falls_back_to_second_candidate(monkeypatch):
    """当第一个候选 Token 触发滑块或过期时，应继续尝试第二个候选 Token。"""
    attempts = []
    refresh_called = []

    def token_api(cookie, token):
        attempts.append(token)
        if token == "stale_cookie_token":
            return ws_token.CAPTCHA_NEEDED
        if token == "db_token":
            return "valid_access_token_123"
        return None

    def refresh(cookie):
        refresh_called.append(cookie)
        return None, None

    monkeypatch.setattr(ws_token, "_call_token_api", token_api)
    monkeypatch.setattr(ws_token, "refresh_m_h5_tk", refresh)

    cookie_str = "_m_h5_tk=stale_cookie_token; unb=123456"
    result = ws_token.get_ws_token_with_refreshed_m_h5_tk(cookie_str, "db_token")

    assert result == ("valid_access_token_123", "db_token", None, None)
    assert attempts == ["stale_cookie_token", "db_token"]
    assert len(refresh_called) == 0


def test_ws_token_heals_via_refresh_after_captcha_or_expired(monkeypatch):
    """当候选 Token 均触发滑块或过期时，应通过 refresh_m_h5_tk 自愈并获取新 Token。"""
    attempts = []

    def token_api(cookie, token):
        attempts.append(token)
        if token == "stale_token":
            return ws_token.SESSION_EXPIRED
        if token == "refreshed_token":
            return "healed_access_token_456"
        return None

    def refresh(cookie):
        return "_m_h5_tk=refreshed_token; unb=123456", "refreshed_token"

    monkeypatch.setattr(ws_token, "_call_token_api", token_api)
    monkeypatch.setattr(ws_token, "refresh_m_h5_tk", refresh)

    cookie_str = "_m_h5_tk=stale_token; unb=123456"
    result = ws_token.get_ws_token_with_refreshed_m_h5_tk(cookie_str, "stale_token")

    assert result == ("healed_access_token_456", "refreshed_token", None, "_m_h5_tk=refreshed_token; unb=123456")
    assert attempts == ["stale_token", "refreshed_token"]


@pytest.mark.asyncio
async def test_cookie_keepalive_handles_missing_cookie_field_without_crashing(monkeypatch):
    from app.services import cookie_token_refresher

    state = cookie_token_refresher.AccountRefreshState(account_id=99)
    monkeypatch.setattr(
        cookie_token_refresher,
        "_call_has_login",
        AsyncMock(return_value={"success": False, "error": "CAPTCHA_NEEDED"}),
    )
    status_updated = AsyncMock(return_value=True)
    monkeypatch.setattr(cookie_token_refresher, "_update_cookie_status", status_updated)
    monkeypatch.setattr(cookie_token_refresher, "notify_captcha_required", AsyncMock())
    monkeypatch.setattr(
        "app.services.remote_slider_config.is_trigger_scene_enabled",
        AsyncMock(return_value=False),
    )

    res = await cookie_token_refresher._do_cookie_keepalive(state)
    assert res is False
    assert status_updated.await_args.kwargs["expected_cookie"] == ""

