"""扫码登录 Playwright 浏览器会话的单元测试（不启动真实浏览器）。"""
import time
import threading
from pathlib import Path
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
        self.verification_text = ""

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

    @property
    def frames(self):
        return [self]

    def goto(self, url, **_kwargs):
        self._env.visited.append(url)

    def set_default_timeout(self, _timeout):
        pass

    def locator(self, selector):
        if selector == "body":
            return SimpleNamespace(inner_text=lambda **kwargs: self._env.verification_text)
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

    @property
    def pages(self):
        return [self.new_page()]

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


def test_verification_keeps_browser_and_credentials_pending_then_resumes(monkeypatch):
    env = _Env(cookie_after_polls=1)
    env.verification_text = "请完成人脸识别"
    monkeypatch.setattr(qlb, "sync_playwright", _fake_sync_playwright(env))
    worker = qlb.QrLoginWorker(timeout=10, headless=False).start()
    try:
        worker.wait_qr_ready(timeout=5)
        snap = _wait_status(worker, "verification_required")
        assert snap["cookies"] is None
        assert "完成验证" in snap["message"]
        assert env.visited == [qlb.LOGIN_URL]
        env.verification_text = ""
        assert _wait_status(worker, "confirmed")["cookies"]["unb"] == "424242"
    finally:
        worker.cancel()
        worker.join(5)


def test_verification_in_popup_frame_and_detached_frames():
    class DetachedFrame:
        def locator(self, selector):
            raise qlb.PlaywrightError("Frame detached")

    env = _Env()
    env.verification_text = "请拖动滑块完成验证"
    context = SimpleNamespace(pages=[
        SimpleNamespace(frames=[DetachedFrame()]),
        SimpleNamespace(frames=[_FakePage(env)]),
    ])
    assert qlb.needs_verification(context)


def test_real_login_page_copy_never_trips_verification_gate():
    """真实登录页正文绝不能触发验证闸门，挑战文案仍然必须命中。"""
    fixture = Path(__file__).parent / "fixtures" / "goofish_login_page_text.txt"
    rendered = "".join(
        line for line in fixture.read_text(encoding="utf-8").splitlines(keepends=True)
        if not line.startswith("#")
    )
    assert rendered.strip()
    assert not qlb.text_needs_verification(rendered)
    # 被剔除的通用词出现在普通文案里时同样不得阻塞登录。
    assert not qlb.text_needs_verification("账号安全验证记录：身份验证状态正常")
    assert not qlb.text_needs_verification("了解人脸验证和刷脸登录的隐私政策")
    # 挑战界面文案必须继续命中，否则验证等待逻辑会失效。
    assert qlb.text_needs_verification("请拖动滑块完成验证")
    assert qlb.text_needs_verification("拖动滑块完成验证")
    assert qlb.text_needs_verification("请按住滑动验证")
    assert qlb.text_needs_verification("按住滑动验证")
    assert qlb.text_needs_verification("请按住滑块，拖动到最右边")
    assert qlb.text_needs_verification("向右滑动完成验证")
    assert qlb.text_needs_verification("拖动滑块")
    assert qlb.text_needs_verification("滑动验证")
    assert qlb.text_needs_verification("请完成人脸识别")


def test_verification_resumes_to_prior_status_instead_of_claiming_scan(monkeypatch):
    """验证在扫码前结束时必须回到未扫码状态，不能谎报“已成功扫码”。"""
    env = _Env(cookie_after_polls=0)  # 始终没有 Cookie，验证结束后停在未扫码
    env.verification_text = "请完成人脸识别"
    monkeypatch.setattr(qlb, "sync_playwright", _fake_sync_playwright(env))
    worker = qlb.QrLoginWorker(timeout=15).start()
    try:
        worker.wait_qr_ready(timeout=5)
        _wait_status(worker, "verification_required")
        env.verification_text = ""
        # 旧实现会无条件落到 scaned，这里必须回到 new（回归保护）。
        _wait_status(worker, "new")
        assert worker.snapshot()["status"] != "scaned"
    finally:
        worker.cancel()
        worker.join(5)


def test_cancelling_during_verification_closes_browser_without_saving(monkeypatch):
    env = _Env()
    env.verification_text = "请进行人脸验证"
    browser = _FakeBrowser(env)
    monkeypatch.setattr(qlb, "sync_playwright", _fake_sync_playwright(env))
    monkeypatch.setattr(qlb, "launch_browser", lambda *args, **kwargs: browser)
    worker = qlb.QrLoginWorker(timeout=10).start()
    worker.wait_qr_ready(timeout=5)
    _wait_status(worker, "verification_required")
    worker.cancel()
    worker.join(5)
    assert browser.closed
    assert worker.snapshot()["status"] == "cancelled"
    assert worker.snapshot()["cookies"] is None


def test_native_host_factory_takes_precedence(monkeypatch):
    from app.core import xianyu_qr_login as sessions
    native_worker = object()
    monkeypatch.setattr(sessions, "desktop_worker_factory", lambda **kwargs: native_worker)
    assert sessions._create_worker(timeout=10) is native_worker
    monkeypatch.setattr(sessions, "desktop_worker_factory", None)
    assert sessions._create_worker(timeout=10)._headless is True


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
