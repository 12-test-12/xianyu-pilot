import pytest

from app.services import ws_token


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
