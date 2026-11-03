"""Embedded Chromium window for the official Xianyu QR login."""
from PySide6.QtCore import QTimer,QUrl,QUrlQuery,Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel,QMainWindow,QVBoxLayout,QWidget
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView


LOGIN_URL=("https://passport.goofish.com/mini_login.htm?lang=zh_CN&appName=xianyu"
    "&appEntrance=default&styleType=vertical&bizParams=&notLoadSsoView=false"
    "&notKeepLogin=false&isMobile=false&qrCodeFirst=true")
ALLOWED_HOSTS=("goofish.com","taobao.com","tmall.com","alipay.com","alipayobjects.com",
    "alicdn.com","alicdn.net","mmstat.com")
PASSIVE_SCHEMES=("about","data","blob")


def is_allowed(url):
    target=QUrl(url) if isinstance(url,str) else url
    if not target.isValid():
        return False
    if not target.toString():
        return True
    scheme=target.scheme().lower()
    if scheme in PASSIVE_SCHEMES:
        return True
    if scheme not in ("http","https"):
        return False
    host=(target.host() or "").lower().rstrip(".")
    if not host:
        return True
    return any(host==domain or host.endswith("."+domain) for domain in ALLOWED_HOSTS)


def _text(value):
    if value is None:
        return ""
    if isinstance(value,str):
        return value
    try:
        return bytes(value.data() if hasattr(value,"data") else value).decode("utf-8","ignore")
    except (TypeError,ValueError):
        return str(value)


def _field(item,key):
    value=item.get(key) if isinstance(item,dict) else getattr(item,key,None)
    return value() if callable(value) else value


def cookie_header(items):
    order=[];values={}
    for item in items:
        name=_text(_field(item,"name"))
        value=_text(_field(item,"value"))
        if not name or not value:
            continue
        if name not in values:
            order.append(name)
        values[name]=value
    return "; ".join(f"{name}={values[name]}" for name in order)


def has_login(cookie):
    for part in (cookie or "").split(";"):
        name,_,value=part.partition("=")
        if name.strip()=="unb" and value.strip():
            return True
    return False


def parse_login_target(url):
    target=QUrl(url) if isinstance(url,str) else url
    if target.scheme().lower()!="xianyu-desktop":
        return False,None
    if (target.host() or target.path().lstrip("/")).lower()!="login":
        return False,None
    raw=QUrlQuery(target).queryItemValue("accountId")
    try:
        account=int(raw) if raw is not None else None
    except ValueError:
        account=None
    return True,account if account is not None and account>0 else None


class LoginPage(QWebEnginePage):
    def acceptNavigationRequest(self,url,_kind,is_main_frame):
        if is_allowed(url):
            return True
        if is_main_frame:
            QDesktopServices.openUrl(url)
        return False

    def createWindow(self,_kind):
        return None

    def javaScriptConsoleMessage(self,*_args):
        pass  # Never write page contents or secrets to native logs.


class LoginWindow(QMainWindow):
    cookies_ready=Signal(str)
    cancelled=Signal()

    def __init__(self,profile=None,parent=None):
        super().__init__(parent)
        self.setWindowTitle("闲鱼登录 · 请用闲鱼 App 扫码")
        self.resize(420,700)
        self.profile=profile if profile is not None else QWebEngineProfile(self)
        self.completed=False
        self.jar={}
        self.profile.cookieStore().cookieAdded.connect(self.collect)
        central=QWidget(self)
        layout=QVBoxLayout(central)
        layout.setContentsMargins(14,12,14,12)
        layout.setSpacing(8)
        hint=QLabel("请使用闲鱼 App 扫码登录；扫码成功后自动完成，无需手动关闭本窗口。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.view=QWebEngineView(central)
        self.page=LoginPage(self.profile,self.view)
        self.view.setPage(self.page)
        layout.addWidget(self.view,1)
        self.setCentralWidget(central)
        self.timer=QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.poll)

    def start(self):
        self.view.setUrl(QUrl(LOGIN_URL))
        self.timer.start()

    def stop(self):
        self.timer.stop()

    def collect(self,cookie):
        name=_text(cookie.name())
        if name:
            self.jar[name]=_text(cookie.value())

    def poll(self):
        if self.completed:
            return
        self.handle_cookies([{"name":name,"value":value} for name,value in self.jar.items()])
        self.profile.cookieStore().loadAllCookies()

    def handle_cookies(self,items):
        header=cookie_header(items)
        if self.completed or not has_login(header):
            return False
        self.completed=True
        self.stop()
        self.cookies_ready.emit(header)
        return True

    def closeEvent(self,event):
        self.stop()
        if not self.completed:
            self.cancelled.emit()
        event.accept()
