"""闲鱼扫码登录的 Playwright 浏览器会话，桌面版显示窗口供用户完成验证。

参照 ai-goofish-monitor 的 account_login_service：由真实 Chromium 打开
passport 登录页并完整执行登录跳转。后端 requests 无法执行
login_token/login.do 返回的 HTML/JS，Cookie 里始终拿不到 unb；浏览器
上下文内扫码、换票、采集一气呵成，二维码直接截取页面 #qrcode-img。
"""
import base64
import logging
import os
import shutil
import threading
import time

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except ImportError:  # 依赖缺失时 worker 上报友好错误，不阻断 API 启动。
    sync_playwright = None

    class PlaywrightError(Exception):
        pass


LOGIN_URL = (
    "https://passport.goofish.com/mini_login.htm?lang=zh_cn&appName=xianyu"
    "&appEntrance=web&styleType=vertical&isMobile=false&qrCodeFirst=true"
    "&notLoadSsoView=true&notKeepLogin=false&stie=77"
)
GOOFISH_HOME = "https://www.goofish.com/"
QR_READY_TIMEOUT = 60  # 包含浏览器启动、页面加载和二维码绘制（秒）
POLL_INTERVAL = 1.0

_EXPIRED_WORDS = ("二维码已失效", "二维码已过期", "二维码失效", "二维码过期")
_SCANNED_WORDS = ("扫码成功", "扫描成功", "已扫码", "请在手机")
_VERIFICATION_WORDS = ("人脸识别", "人脸验证", "刷脸", "安全验证", "身份验证", "滑动验证", "拖动滑块", "请完成验证")


def needs_verification(context) -> bool:
    """检查登录页、验证 iframe 和弹出页，不回传包含票据的页面内容。"""
    for page in context.pages:
        for frame in page.frames:
            try:
                text = frame.locator("body").inner_text(timeout=500)
                if any(word in text for word in _VERIFICATION_WORDS):
                    return True
            except PlaywrightError:
                continue  # 登录跳转可能同时销毁 frame，下一轮再检查。
    return False


class QrLoginUnavailableError(RuntimeError):
    """浏览器或依赖不可用，扫码登录无法启动；message 面向最终用户。"""


def has_login_cookies(cookies) -> bool:
    """Anonymous mtop tokens alone do not prove a completed login."""
    now = time.time()
    names = set()
    for cookie in cookies or []:
        domain = str(cookie.get("domain") or "").lower().lstrip(".")
        if not (domain == "goofish.com" or domain.endswith(".goofish.com")):
            continue
        if not cookie.get("value"):
            continue
        expires = cookie.get("expires", -1)
        if expires != -1 and expires <= now:
            continue
        names.add(cookie.get("name") or "")
    return {"unb", "cookie2"}.issubset(names)


def login_cookie_jar(cookies) -> dict:
    """只导出可发送给闲鱼首页的 Cookie，避免跨域同名凭据覆盖。"""
    now = time.time()
    jar = {}
    for cookie in cookies or []:
        domain = str(cookie.get("domain") or "").lower().lstrip(".")
        if domain not in ("goofish.com", "www.goofish.com"):
            continue
        path = str(cookie.get("path") or "/")
        if path != "/":
            continue
        expires = cookie.get("expires", -1)
        if expires != -1 and expires <= now:
            continue
        if cookie.get("name") and cookie.get("value"):
            jar[cookie["name"]] = cookie["value"]
    return jar


def classify_qr_panel(text: str) -> str:
    """扫码面板文案 → new / scaned / expired；识别不到时保持 new。"""
    text = text or ""
    if any(word in text for word in _EXPIRED_WORDS):
        return "expired"
    if any(word in text for word in _SCANNED_WORDS):
        return "scaned"
    return "new"


def browser_channels(preferred: str | None = None) -> list:
    """本机 Chromium 发行版的尝试顺序：系统 Chrome/Edge 优先，最后回落自带 Chromium。"""
    return list(dict.fromkeys([preferred or "chrome", "msedge", "chrome", None]))


def channel_name(channel) -> str:
    return {
        "chrome": "Chrome",
        "msedge": "Edge",
        None: "Playwright 自带 Chromium",
    }.get(channel, str(channel))


def is_missing_browser_error(error) -> bool:
    message = str(error).lower()
    return (
        "executable doesn't exist" in message
        or "executable does not exist" in message
        or ("distribution" in message and "is not found" in message)
    )


def launch_browser(playwright, *, headless: bool = True):
    """按优先级启动可用浏览器；全部缺失时抛 QrLoginUnavailableError。"""
    preferred = "msedge" if os.getenv("LOGIN_IS_EDGE", "false").lower() == "true" else "chrome"
    channels = browser_channels(preferred)
    for index, channel in enumerate(channels):
        try:
            return playwright.chromium.launch(headless=headless, channel=channel, timeout=15_000)
        except PlaywrightError as error:
            if not is_missing_browser_error(error):
                raise QrLoginUnavailableError(
                    f"{channel_name(channel)} 启动失败，请检查本机浏览器环境后重试。"
                ) from error
            if index + 1 == len(channels):
                raise QrLoginUnavailableError(
                    "未找到可用的浏览器（Chrome / Edge / Chromium）。"
                    "请安装 Google Chrome 或 Microsoft Edge，"
                    "或在服务端 Python 环境执行 python -m playwright install chromium 后重试。"
                ) from error
    raise QrLoginUnavailableError("未找到可用的浏览器，请稍后重试。")  # 不会到达


def _ensure_playwright_env() -> None:
    """若未配置 PLAYWRIGHT_NODEJS_PATH 且系统存在 node，优先指向系统 node 避免驱动加载异常。"""
    if "PLAYWRIGHT_NODEJS_PATH" not in os.environ:
        node = shutil.which("node")
        if node and os.path.isfile(node):
            os.environ["PLAYWRIGHT_NODEJS_PATH"] = node


class QrLoginWorker:
    """在专属守护线程里跑完整个浏览器登录流程。

    Playwright 同步 API 只能在启动它的线程里使用，因此扫码、状态轮询、
    Cookie 采集全部封装在线程内；HTTP 请求线程只读取 snapshot()。
    """

    def __init__(self, *, timeout: int = 300, headless: bool = True):
        self._timeout = timeout
        self._headless = headless
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread = None
        self._status = "starting"
        self._qr_image = None
        self._cookies = None
        self._error = None

    def start(self):
        self._thread = threading.Thread(
            target=self._run, name="qr-login-browser", daemon=True,
        )
        self._thread.start()
        return self

    def cancel(self):
        with self._lock:
            self._cancel.set()
            if self._status not in ("confirmed", "failed", "expired", "cancelled"):
                self._status = "cancelled"
            self._qr_image = None
            self._cookies = None

    def join(self, timeout: float | None = None):
        if self._thread is not None:
            self._thread.join(timeout)

    def snapshot(self) -> dict:
        with self._lock:
            result = {
                "status": self._status,
                "qr_image": self._qr_image,
                "cookies": self._cookies,
                "error": self._error,
            }
            if self._status == "verification_required":
                result["message"] = (
                    "闲鱼要求人脸或安全验证，请在程序内登录窗口或闲鱼 App 中完成，再点击窗口中的完成验证按钮；请勿刷新二维码。"
                    if not self._headless else
                    "闲鱼要求人脸或安全验证，请在闲鱼 App 中完成，系统会继续等待；若验证只出现在网页端，请使用桌面版重新登录。"
                )
            return result

    def wait_qr_ready(self, timeout: float = QR_READY_TIMEOUT) -> str:
        """阻塞直到二维码截图就绪；失败抛 QrLoginUnavailableError。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            snap = self.snapshot()
            if snap["qr_image"]:
                return snap["qr_image"]
            if snap["status"] in ("failed", "expired", "cancelled"):
                raise QrLoginUnavailableError(
                    snap["error"] or "二维码生成失败，请稍后重试。"
                )
            time.sleep(0.1)
        self.cancel()
        raise QrLoginUnavailableError("二维码生成超时，请检查网络后重试。")

    def _set(self, *, status=None, qr_image=None, cookies=None, error=None):
        with self._lock:
            if self._cancel.is_set() or self._status in ("confirmed", "failed", "expired", "cancelled"):
                return
            if status is not None:
                self._status = status
            if qr_image is not None:
                self._qr_image = qr_image
            if cookies is not None:
                self._cookies = cookies
            if error is not None:
                self._error = error

    def _run(self):
        deadline = time.monotonic() + self._timeout
        try:
            if self._cancel.is_set():
                return
            if sync_playwright is None:
                raise QrLoginUnavailableError(
                    "未安装 Playwright 依赖，无法生成扫码二维码；"
                    "请在服务端执行 pip install playwright "
                    "并运行 python -m playwright install chromium 后重试。"
                )
            _ensure_playwright_env()
            with sync_playwright() as playwright:
                browser = launch_browser(playwright, headless=self._headless)
                try:
                    context = browser.new_context(
                        viewport={"width": 1000, "height": 760}, locale="zh-CN",
                    )
                    page = context.new_page()
                    page.set_default_timeout(2000)
                    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
                    qr = page.locator("#qrcode-img")
                    qr.locator("canvas, img:visible").first.wait_for(
                        state="visible", timeout=20_000,
                    )
                    image = "data:image/png;base64," + base64.b64encode(
                        qr.screenshot()
                    ).decode("ascii")
                    self._set(status="new", qr_image=image)
                    while not self._cancel.is_set():
                        if time.monotonic() >= deadline:
                            self._set(status="expired", error="登录或安全验证超时，请重新生成二维码。")
                            return
                        # 验证期间保留同一浏览器上下文，不能跳首页打断验证。
                        if needs_verification(context):
                            self._set(status="verification_required")
                            self._cancel.wait(POLL_INTERVAL)
                            continue
                        if self.snapshot()["status"] == "verification_required":
                            self._set(status="scaned")
                        try:
                            keep_login = page.locator(".keep-login-confirm-btn.primary:visible")
                            if keep_login.count():
                                keep_login.first.click(timeout=1000)
                        except PlaywrightError:
                            pass

                        try:
                            cookies = context.cookies()
                        except PlaywrightError:
                            cookies = []

                        if has_login_cookies(cookies):
                            try:
                                page.goto(
                                    GOOFISH_HOME,
                                    wait_until="domcontentloaded",
                                    timeout=15_000,
                                )
                            except PlaywrightError as exc:
                                logger.warning("访问闲鱼首页异常，尝试沿用当前登录凭据: %s", exc)
                            state = context.storage_state()
                            candidate_cookies = (
                                state.get("cookies")
                                if has_login_cookies(state.get("cookies"))
                                else context.cookies()
                            )
                            if not has_login_cookies(candidate_cookies):
                                raise QrLoginUnavailableError(
                                    "未获取到有效的闲鱼登录状态，请重新扫码。"
                                )
                            jar = login_cookie_jar(candidate_cookies)
                            if needs_verification(context):
                                self._set(status="verification_required")
                                continue
                            if not jar.get("unb") or not jar.get("cookie2"):
                                raise QrLoginUnavailableError("未获取到有效的闲鱼登录状态，请重新扫码。")
                            self._set(status="confirmed", cookies=jar)
                            return

                        try:
                            panel = page.locator(".qrcode-login:visible")
                            if panel.count():
                                status = classify_qr_panel(panel.first.inner_text())
                                if status == "expired":
                                    self._set(status="expired")
                                    return
                                if status == "scaned":
                                    self._set(status="scaned")
                        except PlaywrightError:
                            pass
                        self._cancel.wait(POLL_INTERVAL)
                    self._set(status="cancelled")
                finally:
                    browser.close()
        except QrLoginUnavailableError as exc:
            logger.warning("扫码登录浏览器不可用: %s", exc)
            self._set(status="failed", error=str(exc))
        except PlaywrightError as exc:
            logger.error("Playwright 异常: %s", exc)
            self._set(status="failed", error="浏览器运行异常，请检查本机浏览器或重试。")
        except Exception as exc:
            # 不回显页面 URL、二维码 token 或 Cookie，避免写进日志。
            logger.error("扫码登录浏览器运行失败 errorType=%s", type(exc).__name__)
            self._set(status="failed", error="二维码生成失败，请稍后重试。")
