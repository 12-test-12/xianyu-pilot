"""扫码登录 Playwright 浏览器会话的单元测试（不启动真实浏览器）。"""
import time
import threading
from types import SimpleNamespace

import pytest
from unittest.mock import patch

from app.core import qr_login_browser as qlb
from app.core.xianyu_qr_login import (
    QrLoginUnavailableError,
    cleanup_all,
    generate_qrcode,
)


_LOGIN_COOKIES = [
    {"name": "unb", "value": "424242", "domain": ".goofish.com", "expires": -1},
    {"name": "cookie2", "value": "ck-value", "domain": ".goofish.com", "expires": -1},
]


class _Env:
    """脚本化的一次浏览器登录时间线。"""

    def __init__(self, *, panel_text="", cookie_after_polls=1):
        self.panel_text = panel_text
        self.cookie_after_polls = cookie_after_polls
        self.polls = 0
        self.visited = []

    def cookies(self):
        self.polls += 1
        if self.cookie_after_polls and self.polls >= self.cookie_after_polls:
            return list(_LOGIN_COOKIES)
        return []

    def storage_cookies(self):
        return list(_LOGIN_COOKIES)


class _FakeQrLocator:
    @property
    def first(self):
        return self

    def locator(self, _selector):
        return self

    def wait_for(self, **_kwargs):
        return None

    def screenshot(self):
        return b"png-bytes"


class _FakeEmptyLocator:
    def count(self):
        return 0

    def click(self):
        raise AssertionError("空定位器不应被点击")


class _FakePanelLocator:
    def __init__(self, env):
        self._env = env

    def count(self):
        return 1 if self._env.panel_text else 0

    @property
    def first(self):
        return self

    def inner_text(self):
        return self._env.panel_text


class _FakePage:
    def __init__(self, env):
        self._env = env

    def goto(self, url, **_kwargs):
        self._env.visited.append(url)

    def set_default_timeout(self, _timeout):
        pass

    def locator(self, selector):
        if selector == "#qrcode-img":
            return _FakeQrLocator()
        if selector == ".keep-login-confirm-btn.primary:visible":
            return _FakeEmptyLocator()
        if selector == ".qrcode-login:visible":
            return _FakePanelLocator(self._env)
        raise AssertionError(f"unexpected locator {selector}")


class _FakeContext:
    def __init__(self, env):
        self._env = env

    def new_page(self):
        return _FakePage(self._env)

    def cookies(self):
        return self._env.cookies()

    def storage_state(self):
        return {"cookies": self._env.storage_cookies()}


class _FakeBrowser:
    def __init__(self, env):
        self._env = env
        self.closed = False

    def new_context(self, **_kwargs):
        return _FakeContext(self._env)

    def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, env, *, missing=()):
        self._env = env
        self._missing = set(missing)
        self.launched = []

    def launch(self, *, headless=True, channel=None, timeout=None):
        self.launched.append(channel)
        if channel in self._missing:
            raise qlb.PlaywrightError(f"Chromium distribution '{channel}' is not found")
        return _FakeBrowser(self._env)


def _fake_sync_playwright(env, *, missing=()):
    """返回可直接替换 qlb.sync_playwright 的工厂：sync_playwright() -> CM。"""
    chromium = _FakeChromium(env, missing=missing)

    class _CM:
        def __enter__(self):
            return SimpleNamespace(chromium=chromium)

        def __exit__(self, *_args):
            return False

    return lambda: _CM()


def _wait_status(worker, wanted, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = worker.snapshot()
        if snap["status"] == wanted:
            return snap
        time.sleep(0.02)
    raise AssertionError(f"worker 未进入 {wanted} 状态: {worker.snapshot()}")


def test_has_login_cookies_requires_unb_and_cookie2_on_goofish():
    assert qlb.has_login_cookies(_LOGIN_COOKIES) is True
    assert qlb.has_login_cookies(_LOGIN_COOKIES[:1]) is False
    assert qlb.has_login_cookies([]) is False
    # 非 goofish 域名的同名 Cookie 不算数
    wrong_domain = [{"name": "unb", "value": "1", "domain": ".example.com", "expires": -1},
                    {"name": "cookie2", "value": "2", "domain": ".example.com", "expires": -1}]
    assert qlb.has_login_cookies(wrong_domain) is False
    # 过期 Cookie 不算数
    expired = [{"name": "unb", "value": "1", "domain": "goofish.com", "expires": 1},
               {"name": "cookie2", "value": "2", "domain": "goofish.com", "expires": 1}]
    assert qlb.has_login_cookies(expired) is False


def test_classify_qr_panel_texts():
    assert qlb.classify_qr_panel("二维码已失效，请刷新") == "expired"
    assert qlb.classify_qr_panel("二维码已过期") == "expired"
    assert qlb.classify_qr_panel("扫码成功，请在手机上确认") == "scaned"
    assert qlb.classify_qr_panel("请在手机上确认登录") == "scaned"
    assert qlb.classify_qr_panel("请使用闲鱼 App 扫码") == "new"
    assert qlb.classify_qr_panel("") == "new"


def test_export_drops_cross_domain_expired_and_wrong_path_cookies():
    cookies = list(_LOGIN_COOKIES) + [
        {"name": "m_test", "value": "val1", "domain": ".goofish.com", "path": None},
        {"name": "m_test2", "value": "val2", "domain": ".goofish.com", "path": ""},
        {"name": "unb", "value": "wrong", "domain": ".taobao.com"},
        {"name": "cookie2", "value": "wrong", "domain": "passport.goofish.com"},
        {"name": "unb", "value": "wrong", "domain": ".goofish.com", "path": "/login"},
        {"name": "cookie2", "value": "wrong", "domain": ".goofish.com", "expires": 1},
    ]
    assert qlb.login_cookie_jar(cookies) == {
        "unb": "424242",
        "cookie2": "ck-value",
        "m_test": "val1",
        "m_test2": "val2",
    }


def test_cancel_during_login_prevents_late_credentials():
    worker = qlb.QrLoginWorker()
    worker._set(status="new", qr_image="qr")
    worker.cancel()
    worker._set(status="confirmed", cookies={"unb": "late"})
    assert worker.snapshot() == {"status": "cancelled", "qr_image": None, "cookies": None, "error": None}


def test_browser_channels_deduplicates_preferred():
    assert qlb.browser_channels("chrome") == ["chrome", "msedge", None]
    assert qlb.browser_channels("msedge") == ["msedge", "chrome", None]
    assert qlb.browser_channels(None) == ["chrome", "msedge", None]


def test_launch_browser_falls_back_when_chrome_missing():
    env = _Env()
    chromium = _FakeChromium(env, missing={"chrome"})
    result = qlb.launch_browser(SimpleNamespace(chromium=chromium))
    assert isinstance(result, _FakeBrowser)
    assert chromium.launched == ["chrome", "msedge"]


def test_launch_browser_reports_actionable_error_when_all_missing():
    chromium = _FakeChromium(_Env(), missing={"chrome", "msedge", None})
    with pytest.raises(qlb.QrLoginUnavailableError) as excinfo:
        qlb.launch_browser(SimpleNamespace(chromium=chromium))
    assert "playwright install chromium" in str(excinfo.value)


def test_worker_without_playwright_fails_with_guidance(monkeypatch):
    monkeypatch.setattr(qlb, "sync_playwright", None)
    worker = qlb.QrLoginWorker(timeout=5).start()
    with pytest.raises(QrLoginUnavailableError) as excinfo:
        worker.wait_qr_ready(timeout=5)
    assert "未安装 Playwright" in str(excinfo.value)


def test_worker_completes_login_and_collects_cookies(monkeypatch):
    env = _Env(cookie_after_polls=1)
    monkeypatch.setattr(qlb, "sync_playwright", _fake_sync_playwright(env))
    worker = qlb.QrLoginWorker(timeout=10).start()
    qr_image = worker.wait_qr_ready(timeout=5)
    assert qr_image.startswith("data:image/png;base64,")
    snap = _wait_status(worker, "confirmed")
    assert snap["cookies"]["unb"] == "424242"
    assert snap["cookies"]["cookie2"] == "ck-value"
    # 登录完成后回访 goofish 首页，与参考项目一致
    assert env.visited[-1] == qlb.GOOFISH_HOME


def test_worker_recovers_if_homepage_goto_fails_with_playwright_error(monkeypatch):
    class _FailingGotoPage(_FakePage):
        def goto(self, url, **_kwargs):
            if url == qlb.GOOFISH_HOME:
                raise qlb.PlaywrightError("net::ERR_CONNECTION_RESET")
            super().goto(url, **_kwargs)

    class _ContextWithFailingPage(_FakeContext):
        def new_page(self):
            return _FailingGotoPage(self._env)

        def storage_state(self):
            return {"cookies": []}

    class _BrowserWithFailingPage(_FakeBrowser):
        def new_context(self, **_kwargs):
            return _ContextWithFailingPage(self._env)

    class _ChromiumWithFailingPage(_FakeChromium):
        def launch(self, **_kwargs):
            return _BrowserWithFailingPage(self._env)

    env = _Env(cookie_after_polls=1)

    class _CM:
        def __enter__(self):
            return SimpleNamespace(chromium=_ChromiumWithFailingPage(env))

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(qlb, "sync_playwright", lambda: _CM())
    worker = qlb.QrLoginWorker(timeout=10).start()
    worker.wait_qr_ready(timeout=5)
    snap = _wait_status(worker, "confirmed")
    assert snap["cookies"]["unb"] == "424242"
    assert snap["cookies"]["cookie2"] == "ck-value"


def test_worker_marks_expired_when_qr_panel_reports_failure(monkeypatch):
    env = _Env(panel_text="二维码已失效，请刷新", cookie_after_polls=0)
    monkeypatch.setattr(qlb, "sync_playwright", _fake_sync_playwright(env))
    worker = qlb.QrLoginWorker(timeout=10).start()
    worker.wait_qr_ready(timeout=5)
    snap = _wait_status(worker, "expired")
    assert snap["qr_image"]


def test_generate_qrcode_propagates_unavailable_and_cancels_worker(monkeypatch):
    class _FailingWorker:
        def __init__(self, *, timeout):
            self.cancelled = False

        def start(self):
            return self

        def cancel(self):
            self.cancelled = True

        def join(self, timeout=None):
            return None

        def wait_qr_ready(self, timeout=None):
            raise QrLoginUnavailableError("未安装 Playwright 依赖，无法生成扫码二维码。")

    failing = {}

    def factory(*, timeout):
        worker = _FailingWorker(timeout=timeout)
        failing["worker"] = worker
        return worker

    with patch("app.core.xianyu_qr_login._create_worker", factory):
        with pytest.raises(QrLoginUnavailableError):
            generate_qrcode(user_id=1, owner_key="browser-test")
    assert failing["worker"].cancelled is True
    cleanup_all()


def test_starting_browser_reserves_capacity(monkeypatch):
    from app.core import xianyu_qr_login as sessions
    entered, release = threading.Event(), threading.Event()
    results = []

    class BlockingWorker:
        def __init__(self, **kwargs):
            pass

        def start(self):
            entered.set()

        def wait_qr_ready(self, timeout):
            assert release.wait(5)
            return "qr"

        def cancel(self):
            pass

        def join(self, timeout):
            pass

    cleanup_all()
    monkeypatch.setattr(sessions, "MAX_ACTIVE_SESSIONS", 1)
    monkeypatch.setattr(sessions, "_create_worker", BlockingWorker)
    thread = threading.Thread(target=lambda: results.append(generate_qrcode(owner_key="first")))
    thread.start()
    try:
        assert entered.wait(5)
        with pytest.raises(sessions.QrSessionCapacityError):
            generate_qrcode(owner_key="second")
    finally:
        release.set()
        thread.join(5)
        cleanup_all()
    assert len(results) == 1
