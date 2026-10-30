"""CI-only offscreen Chromium test; explicitly does not certify a system tray."""
import json
import os
import time

CONSOLE_PROBE=r"""(() => {
  const rendered = Boolean(document.querySelector('.app-shell .sidebar')) &&
    ['账号','自动发货','卡密','商品','订单','消息','日志'].every(text => document.body.innerText.includes(text));
  if (!rendered) return JSON.stringify({rendered:false});
  if (!window.__xianyuConsoleCheck) {
    window.__xianyuConsoleCheck = {pending:true};
    (async () => {
      const token = sessionStorage.getItem('xianyu_auth_token');
      const headers = {Authorization:'Bearer '+token};
      const checks = {};
      for (const path of ['/xianyu/accounts','/goods','/orders','/orders/today-amount','/cards',
                          '/auto-delivery/sources','/auto-reply/rules','/conversations',
                          '/operation-logs','/business-settings/ai-customer-service','/system/open-source-config']) {
        try { const response=await fetch('/api'+path,{headers}); const body=await response.json();
          checks[path]=response.ok && body.code===200; } catch { checks[path]=false; }
      }
      try {
        const response=await fetch('/api/sse/ticket',{method:'POST',headers});
        const body=await response.json();
        checks.sse=await new Promise(resolve => {
          const stream=new EventSource('/api/sse/subscribe?ticket='+encodeURIComponent(body.data.ticket));
          const timer=setTimeout(()=>{stream.close();resolve(false)},8000);
          stream.onmessage=event=>{clearTimeout(timer);stream.close();resolve(JSON.parse(event.data).type==='connected')};
          stream.onerror=()=>{clearTimeout(timer);stream.close();resolve(false)};
        });
      } catch { checks.sse=false; }
      window.__xianyuConsoleCheck={pending:false,checks};
    })();
  }
  return JSON.stringify({rendered:true,...window.__xianyuConsoleCheck});
})()"""


def check(root,paths,web,port):
    os.environ["QT_QPA_PLATFORM"]="offscreen"
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]+=" --disable-gpu"
    from PySide6.QtCore import QTimer,QUrl
    from PySide6.QtWidgets import QApplication
    from PySide6.QtWebEngineCore import QWebEngineProfileBuilder,QWebEnginePage
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from shiboken6 import delete
    from app.core.instance_lock import SingleInstance
    from app.core.config import Settings
    from app.portable.backend import DesktopBackend
    app=QApplication([])
    result={"ok":False,"trayNativeValidated":False}
    with SingleInstance(root) as instance:
        backend=DesktopBackend(Settings(runtime_mode="desktop",desktop_port=port),web,instance)
        builder=QWebEngineProfileBuilder()
        builder.setPersistentStoragePath(str(paths["profile"]))
        builder.setCachePath(str(paths["cache"]))
        profile=builder.createProfile("portable-check",app)
        if profile is None:
            raise RuntimeError("cannot create portable profile")
        view=QWebEngineView()
        page=QWebEnginePage(profile,view)
        view.setPage(page)
        started=time.monotonic()
        closing=False
        requested=False
        loaded_ok=False
        checking=False
        def read_title(title):
            nonlocal closing,checking
            checking=False
            try:
                probe=json.loads(title)
            except (ValueError,TypeError):
                return
            if probe.get('rendered') and probe.get('pending') is False:
                checks=probe.get('checks',{})
                result.update(ok=bool(checks) and all(checks.values()),originalConsoleRendered=True,apiChecks=checks)
                backend.stop()
                closing=True
        def loaded(ok):
            nonlocal loaded_ok
            loaded_ok=ok
        view.loadFinished.connect(loaded)
        def tick():
            nonlocal closing,requested,checking
            if closing:
                if backend.stopped:
                    app.quit()
                return
            if backend.error or time.monotonic()-started>25:
                backend.stop();closing=True
            elif backend.ready and not requested:
                requested=True
                view.setUrl(QUrl(f"http://127.0.0.1:{port}/"))
            elif loaded_ok and not checking:
                checking=True
                page.runJavaScript(CONSOLE_PROBE,read_title)
        timer=QTimer(app)
        timer.timeout.connect(tick)
        timer.start(100)
        backend.start()
        try:
            app.exec()
        finally:
            backend.stop()
            backend.thread.join()
            timer.stop()
            delete(view)
            delete(profile)
    (root/"logs/webengine-check.json").write_text(json.dumps(result),encoding="utf-8")
    return 0 if result["ok"] else 1
