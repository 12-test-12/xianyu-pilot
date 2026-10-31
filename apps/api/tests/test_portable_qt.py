"""GUI contracts run after GitHub installs Qt; no physical tray certification."""
from pathlib import Path
import os
import sys
from types import SimpleNamespace
import pytest

pytest.importorskip('PySide6',reason='Qt is installed by the GitHub Windows packaging job only')
pytestmark=pytest.mark.skipif(sys.platform!='win32',reason='Windows host')


@pytest.fixture
def console(tmp_path,monkeypatch):
    from app.core import paths
    monkeypatch.setattr(paths,'SOURCE_ROOT',tmp_path)
    for key in ('RUNTIME_MODE','APPDATA','LOCALAPPDATA','XDG_CONFIG_HOME','XDG_CACHE_HOME','XDG_DATA_HOME',
                'QML_DISK_CACHE_PATH','QTWEBENGINE_CHROMIUM_FLAGS','QTWEBENGINE_REMOTE_DEBUGGING',
                'QTWEBENGINE_DISABLE_SANDBOX','TEMP','TMP','TMPDIR','PYTHONDONTWRITEBYTECODE','QT_QPA_PLATFORM'):
        monkeypatch.setenv(key,os.environ.get(key,''))
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from app.portable.bootstrap import configure_environment
    root,locations=configure_environment()
    web=tmp_path/'apps/web/dist'
    web.mkdir(parents=True)
    (web/'favicon.ico').write_bytes((Path(__file__).resolve().parents[2]/'web/public/favicon.ico').read_bytes())
    from app.portable.qt_host import DesktopConsole,QSystemTrayIcon
    from app.services.delivery_gate import DeliveryGate
    monkeypatch.setattr(QSystemTrayIcon,'isSystemTrayAvailable',staticmethod(lambda:True))
    # The icon API is real; only shell availability is simulated in this test.
    class Backend:
        config=SimpleNamespace(desktop_port=19177)
        runtime=object()
        gate=DeliveryGate()
        ready=True
        stopped=False
        stops=0
        def pause(self,reason='manual'):self.gate.block(reason)
        def resume(self,reason='manual'):self.gate.clear(reason)
        def stop(self):self.stops+=1
    # A separate pytest process owns the only QApplication in this job.
    c=DesktopConsole(Backend(),locations)
    yield c,root
    c.dispose()


def test_close_hides_window_and_keeps_backend_running(console):
    c,root=console
    c.show()
    c.window.close()
    assert not c.window.isVisible() and c.backend.stops==0
    assert c.tray.isVisible() and not c.first_hide
    assert Path(c.profile.persistentStoragePath()).is_relative_to(root)
    assert Path(c.profile.cachePath()).is_relative_to(root)


def test_repeated_status_does_not_repaint_native_status_bar(console):
    from app.portable.qt_host import LABELS
    c,_=console
    messages=[]
    c.window.statusBar().messageChanged.connect(messages.append)
    c.render('offline')
    for _ in range(20):c.render('offline')
    assert messages==[LABELS['offline']]


def test_window_icon_persistent_cache_and_stable_loading_background(console):
    from PySide6.QtWebEngineCore import QWebEngineProfile
    c,_=console
    assert not c.app.windowIcon().isNull()
    assert c.profile.httpCacheType()==QWebEngineProfile.HttpCacheType.DiskHttpCache
    assert c.page.backgroundColor().name()=='#f6f9ff'
    assert c.stack.currentWidget() is c.startup_label
    c.on_load(True)
    assert c.stack.currentWidget() is c.view


def test_pause_toggle_and_resume_do_not_clear_network_pause(console):
    c,root=console
    c.toggle_delivery()
    assert c.backend.gate.reasons==('manual',)
    c.backend.pause('network')
    c.toggle_delivery()
    assert c.backend.gate.reasons==('network',)
    c.begin_shutdown()
    assert c.exiting and c.backend.stops==1


def test_native_power_bridge_pauses_and_requests_resume(console):
    import ctypes
    from ctypes import wintypes
    c,root=console
    msg=wintypes.MSG()
    msg.message=0x218;msg.wParam=4
    c.window.nativeEvent('windows_generic_MSG',ctypes.addressof(msg))
    assert 'suspend' in c.backend.gate.reasons
    msg.wParam=18
    c.window.nativeEvent('windows_generic_MSG',ctypes.addressof(msg))
    assert 'suspend' not in c.backend.gate.reasons


def test_original_platform_images_load_but_external_active_requests_are_blocked(console):
    from PySide6.QtCore import QUrl
    from PySide6.QtWebEngineCore import QWebEngineUrlRequestInfo
    c,_=console
    resource=QWebEngineUrlRequestInfo.ResourceType
    class Request:
        blocked=False
        def __init__(self,url,kind):self.url,self.kind=url,kind
        def requestUrl(self):return QUrl(self.url)
        def firstPartyUrl(self):return QUrl('http://127.0.0.1:19177/')
        def resourceType(self):return self.kind
        def block(self,value):self.blocked=value
    image=Request('https://example.com/goods.jpg',resource.ResourceTypeImage)
    script=Request('https://example.com/script.js',resource.ResourceTypeScript)
    api=Request('https://example.com/api',resource.ResourceTypeXhr)
    local=Request('http://127.0.0.1:19177/api/goods',resource.ResourceTypeXhr)
    for request in (image,script,api,local):c.interceptor.interceptRequest(request)
    assert not image.blocked and not local.blocked
    assert script.blocked and api.blocked
