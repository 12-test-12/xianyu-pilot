from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.file_secrets import resolve_file_secret_values
from app.services import captcha_solver


def test_internal_api_token_uses_internal_api_token_file(tmp_path, monkeypatch):
    token_file = tmp_path / "internal_api_token"
    token_file.write_text("file-token\n", encoding="utf-8")
    values = resolve_file_secret_values(
        {
            "internal_api_token": "",
            "internal_api_token_file": str(token_file),
        },
        secret_fields=("internal_api_token",),
    )
    monkeypatch.setattr(captcha_solver.settings, "internal_api_token", values["internal_api_token"])
    monkeypatch.setenv("INTERNAL_API_TOKEN", "different-environment-token")

    assert captcha_solver._resolve_internal_api_token() == "file-token"


def test_messages_page_image_send_paths_only_refresh_conversations():
    source_path = Path(__file__).resolve().parents[2] / "web" / "src" / "pages" / "MessagesPage.vue"
    source = source_path.read_text(encoding="utf-8")

    assert source.count("await refreshAll(true)") == 1
    assert source.count("await loadConversations(true, { background: true })") >= 6


@pytest.mark.asyncio
async def test_verify_cookie_via_token_api_uses_asyncio_to_thread(monkeypatch):
    """验证 _verify_cookie_via_token_api 正确调用 asyncio.to_thread 且根据 ws_token 返回分类。"""
    class _MockResult:
        def mappings(self):
            return self

        def first(self):
            return {
                "encrypted_cookie": "test-encrypted-cookie",
                "encrypted_token": "test-encrypted-token",
            }

    class _MockDb:
        async def execute(self, *args, **kwargs):
            return _MockResult()

    class _MockSessionCtx:
        async def __aenter__(self):
            return _MockDb()

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    monkeypatch.setattr(captcha_solver, "async_session", lambda: _MockSessionCtx())
    monkeypatch.setattr(captcha_solver, "decrypt_cookie_if_needed", lambda x: f"decrypted_{x}")

    # 1. 成功返回 access_token -> 应返回 "ok"
    monkeypatch.setattr(
        "app.services.ws_token.get_ws_token_with_refreshed_m_h5_tk",
        lambda cookie, token: ("mock-access-token", "token", None, None),
    )
    res_ok = await captcha_solver._verify_cookie_via_token_api(123)
    assert res_ok == "ok"

    # 2. 会话过期 -> 应返回 "expired" 而非 unavailable
    monkeypatch.setattr(
        "app.services.ws_token.get_ws_token_with_refreshed_m_h5_tk",
        lambda cookie, token: (None, None, "expired", None),
    )
    res_expired = await captcha_solver._verify_cookie_via_token_api(123)
    assert res_expired == "expired"

    # 3. 遇到验证码 -> 应返回 "captcha"
    monkeypatch.setattr(
        "app.services.ws_token.get_ws_token_with_refreshed_m_h5_tk",
        lambda cookie, token: (None, None, "captcha", None),
    )
    res_captcha = await captcha_solver._verify_cookie_via_token_api(123)
    assert res_captcha == "captcha"

