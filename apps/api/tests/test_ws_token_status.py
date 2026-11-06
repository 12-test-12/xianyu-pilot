import pytest

from app.services import ws_token


@pytest.mark.parametrize(("response", "status", "refreshes"), [
    (None, "unavailable", True),
    (ws_token.CAPTCHA_NEEDED, "captcha", False),
    (ws_token.SESSION_EXPIRED, "expired", False),
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
