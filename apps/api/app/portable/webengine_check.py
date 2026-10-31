"""CI-only offscreen Chromium test; explicitly does not certify a system tray."""
import json
import os
import time

CONSOLE_PROBE=r"""(() => {
  const rendered = Boolean(document.querySelector('.app-shell .sidebar')) &&
    ['账号','自动发货','卡密','商品','订单','消息','日志'].every(text => document.body.innerText.includes(text));
  if (!rendered) return JSON.stringify({rendered:false,width:innerWidth,booting:Boolean(document.querySelector('.boot-screen'))});
  if (!window.__xianyuConsoleCheck) {
    window.__xianyuConsoleCheck = {pending:true};
    (async () => {
      const token = sessionStorage.getItem('xianyu_auth_token');
      const headers = {Authorization:'Bearer '+token};
      const checks = {};
      for (const path of ['/xianyu/accounts','/goods','/orders','/orders/today-amount','/cards',
                          '/auto-delivery/sources','/auto-delivery/records','/auto-reply/rules','/conversations',
                          '/operation-logs','/business-settings/ai-customer-service','/system/open-source-config','/address-dict/tree']) {
        try { const response=await fetch('/api'+path,{headers}); const body=await response.json();
          checks[path]=response.ok && body.code===200 &&
            (path!=='/address-dict/tree' || body.data?.provinces?.length>0); } catch { checks[path]=false; }
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
      try {
        // Exercise Vue's actual cascader events in bundled Chromium. No account
        // or remote publication is needed for region/online-delivery controls.
        const waitFor=async predicate=>{
          for(let n=0;n<80;n++) { if(predicate())return; await new Promise(r=>setTimeout(r,50)); }
          throw new Error('publish controls timeout');
        };
        location.hash='#/product-publish';
        await waitFor(()=>document.querySelector('.publish-address-cascader select')?.options.length>1);
        const selects=[...document.querySelectorAll('.publish-address-cascader select')];
        const choose=async(index,value)=>{
          selects[index].value=value;
          selects[index].dispatchEvent(new Event('change',{bubbles:true}));
          await new Promise(r=>setTimeout(r,20));
        };
        await choose(0,'北京市');
        await choose(1,'北京市');
        await choose(2,'东城区');
        checks.publishRegion=document.querySelector('.selected-address')?.innerText.includes('东城区') &&
          [...document.querySelectorAll('.option-line')].some(row=>row.innerText.includes('发布地区完整有效') && row.innerText.includes('通过'));
        const shippingRows=[...document.querySelectorAll('.shipping-item')];
        const selfPick=shippingRows.find(row=>row.innerText.includes('支持自提')).querySelector('button');
        selfPick.click();
        shippingRows.find(row=>row.innerText.includes('线上交付')).querySelector('button').click();
        await new Promise(r=>setTimeout(r,20));
        checks.onlineDelivery=selfPick.disabled && selfPick.getAttribute('aria-checked')==='false';
        document.querySelector('.selected-address button').click();
        await new Promise(r=>setTimeout(r,20));
        checks.clearPublishRegion=selects.every(select=>select.value==='');
        await choose(0,'浙江省');
        await choose(1,'杭州市');
        await choose(2,'西湖区');
        checks.changePublishRegion=document.querySelector('.selected-address')?.innerText.includes('西湖区') || false;
      } catch { checks.publishControls=false; }
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
        # Match the real desktop window. The original app intentionally selects
        # MobileLite below 900px; Qt's default 640px view is not a desktop probe.
        view.resize(1180,820)
        view.show()
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
            result['lastProbe']=probe
            if probe.get('rendered') and probe.get('pending') is False:
                checks=probe.get('checks',{})
                result.update(ok=bool(checks) and all(checks.values()),originalConsoleRendered=True,apiChecks=checks)
                view.setUrl(QUrl('about:blank'))
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
                result.update(reason='backend-error' if backend.error else 'console-timeout',
                              backendError=backend.error,backendReady=backend.ready,pageLoaded=loaded_ok)
                view.grab().save(str(root/'logs/webengine-check.png'))
                view.setUrl(QUrl('about:blank'))
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
