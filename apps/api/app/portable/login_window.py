"""在应用内打开官方登录页；凭据只交给后端扫码会话。"""
import base64
import json
import time

from PySide6.QtCore import QObject, Signal, Qt, QTimer, QUrl, QRect, QBuffer, QIODevice
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QMessageBox
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineUrlRequestInterceptor, QWebEnginePermission
from PySide6.QtWebEngineWidgets import QWebEngineView

from app.core.qr_login_browser import (
    QrLoginWorker, LOGIN_URL, GOOFISH_HOME, _VERIFICATION_WORDS,
    TIMEOUT_ERROR, QR_EXPIRED_ERROR,
    has_login_cookies, login_cookie_jar, classify_qr_panel,
)

ALLOWED_HOSTS = ("goofish.com", "taobao.com", "tmall.com", "alipay.com",
                 "alipayobjects.com", "alicdn.com", "alicdn.net", "mmstat.com")


def is_allowed(url):
    if url.scheme() in ("about", "data", "blob"):
        return True
    host = url.host().lower().rstrip(".")
    return (url.scheme() == "https" and not url.userInfo()
            and any(host == domain or host.endswith("." + domain) for domain in ALLOWED_HOSTS))


class LoginRequests(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info):
        if not is_allowed(info.requestUrl()):
            info.block(True)


class LoginPage(QWebEnginePage):
    def __init__(self, profile, view, window):
        super().__init__(profile, view)
        self.window = window
        self.permissionRequested.connect(window.permission_requested)

    def createWindow(self, _kind):
        return self.window.open_popup()

    def acceptNavigationRequest(self, url, _kind, _main):
        return is_allowed(url)

    def javaScriptConsoleMessage(self, *_args):
        pass  # 官方页面的票据和 Cookie 不写入日志。


class EmbeddedWorker(QrLoginWorker):
    def __init__(self, broker, *, timeout):
        super().__init__(timeout=timeout, headless=False)
        self.broker = broker

    def start(self):
        self.broker.open_requested.emit(self)
        return self


class LoginBroker(QObject):
    open_requested = Signal(object)

    def __init__(self, parent):
        super().__init__(parent)
        self.windows = []
        self.open_requested.connect(self.open, Qt.ConnectionType.QueuedConnection)

    def worker(self, *, timeout):
        return EmbeddedWorker(self, timeout=timeout)

    def open(self, worker):
        if worker._cancel.is_set():
            return
        window = LoginWindow(worker, self.parent())
        self.windows.append(window)
        window.finished.connect(lambda: self.windows.remove(window))
        window.show()

    def close(self):
        for window in list(self.windows):
            window.worker.cancel()
            window.close()


class LoginWindow(QDialog):
    def __init__(self, worker, parent=None):
        super().__init__(parent)
        self.worker = worker
        self.deadline = time.monotonic() + worker._timeout
        self.jar = {}
        self.checking = False
        self.visiting_home = False
        self.home_loaded = False
        self.popups = []
        self.setWindowTitle("闲鱼登录与安全验证")
        self.resize(720, 800)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(self)
        self.hint = QLabel("请在官方页面扫码并亲自完成安全验证，再点击“完成验证，添加账号”。请勿关闭此窗口。")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        # 每次新建内存 profile，无旧账号凭据，也不共享控制台权限。
        self.profile = QWebEngineProfile(self)
        self.interceptor = LoginRequests(self.profile)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        self.profile.downloadRequested.connect(lambda download: download.cancel())
        self.view = QWebEngineView(self)
        self.page = LoginPage(self.profile, self.view, self)
        self.view.setPage(self.page)
        self.page.loadFinished.connect(self.loaded)
        self.page.loadStarted.connect(lambda: setattr(self, "home_loaded", False))
        self.profile.cookieStore().cookieAdded.connect(self.collect)
        self.profile.cookieStore().cookieRemoved.connect(self.remove_cookie)
        layout.addWidget(self.view, 1)
        button = QPushButton("完成验证，添加账号", self)
        button.clicked.connect(self.complete)
        layout.addWidget(button)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(500)
        self.finished.connect(self.cleanup)
        self.view.setUrl(QUrl(LOGIN_URL))

    def permission_requested(self, permission):
        camera = permission.permissionType() in (
            QWebEnginePermission.PermissionType.MediaVideoCapture,
            QWebEnginePermission.PermissionType.MediaAudioVideoCapture,
        )
        if camera and is_allowed(permission.origin()):
            answer = QMessageBox.question(self, "安全验证摄像头权限",
                f"官方验证页面 {permission.origin().host()} 请求使用摄像头，是否允许？")
            if answer == QMessageBox.StandardButton.Yes:
                permission.grant()
                return
        permission.deny()

    def open_popup(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("闲鱼官方安全验证")
        dialog.resize(650, 760)
        layout = QVBoxLayout(dialog)
        view = QWebEngineView(dialog)
        page = LoginPage(self.profile, view, self)
        view.setPage(page)
        layout.addWidget(view)
        self.popups.append((dialog, page))
        dialog.show()
        return page

    def loaded(self, ok):
        self.home_loaded = bool(ok and self.visiting_home and self.view.url().host() == "www.goofish.com")

    @staticmethod
    def cookie_key(cookie):
        return (cookie.domain(), cookie.path(), bytes(cookie.name()))

    def collect(self, cookie):
        self.jar[self.cookie_key(cookie)] = {
            "name": bytes(cookie.name()).decode("utf-8", "replace"),
            "value": bytes(cookie.value()).decode("utf-8", "replace"),
            "domain": cookie.domain(), "path": cookie.path(),
            "expires": -1 if cookie.isSessionCookie() else cookie.expirationDate().toSecsSinceEpoch(),
        }

    def remove_cookie(self, cookie):
        self.jar.pop(self.cookie_key(cookie), None)

    def complete(self):
        if self.worker.snapshot()["status"] == "verification_required":
            self.hint.setText("官方页面仍提示安全验证，请完成验证后再添加账号。")
            return
        if not has_login_cookies(list(self.jar.values())):
            self.hint.setText("尚未获取到完整登录凭据，请先在官方页面完成登录和验证。")
            return
        self.visiting_home = True
        self.home_loaded = False
        self.view.setUrl(QUrl(GOOFISH_HOME))

    def poll(self):
        if self.worker._cancel.is_set():
            self.close()
            return
        if time.monotonic() >= self.deadline:
            self.worker._set(status="expired", error=TIMEOUT_ERROR)
            self.close()
            return
        if self.checking:
            return
        self.checking = True
        self.page.runJavaScript("""JSON.stringify((() => {
            const qr = document.querySelector('#qrcode-img');
            const drawn = qr?.querySelector('canvas, img');
            const r = drawn && (drawn.tagName !== 'IMG' || drawn.naturalWidth > 0) ? qr.getBoundingClientRect() : null;
            return {text: document.body?.innerText || '',
                    qr: r && r.width > 0 && r.height > 0 ? [r.x, r.y, r.width, r.height] : null};
        })())""", self.inspect)

    def inspect(self, raw):
        self.checking = False
        if self.worker._cancel.is_set():
            return
        try:
            data = json.loads(raw or "{}")
        except (ValueError, TypeError):
            return
        if data.get("qr") and not self.worker.snapshot()["qr_image"]:
            rect = QRect(*[round(value) for value in data["qr"]])
            image = self.view.grab(rect)
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "PNG")
            self.worker._set(status="new", qr_image="data:image/png;base64," + base64.b64encode(bytes(buffer.data())).decode("ascii"))
        if any(word in data.get("text", "") for word in _VERIFICATION_WORDS):
            self.worker._set(status="verification_required")
            return
        if self.worker.snapshot()["status"] == "verification_required":
            self.worker._set(status="scaned")
        status = classify_qr_panel(data.get("text", ""))
        if status == "expired" and not self.visiting_home:
            self.worker._set(status="expired", error=QR_EXPIRED_ERROR)
            self.close()
            return
        if status == "scaned":
            self.worker._set(status="scaned")
        if self.home_loaded:
            cookies = list(self.jar.values())
            jar = login_cookie_jar(cookies)
            if jar.get("unb") and jar.get("cookie2"):
                self.worker._set(status="confirmed", cookies=jar)
                self.close()

    def cleanup(self, _result):
        from shiboken6 import delete, isValid
        self.timer.stop()
        if self.worker.snapshot()["status"] not in ("confirmed", "expired", "failed"):
            self.worker.cancel()
        # 页面必须先于其 profile 销毁。
        for dialog, page in self.popups:
            if isValid(page):
                delete(page)
            dialog.close()
        if isValid(self.page):
            delete(self.page)
