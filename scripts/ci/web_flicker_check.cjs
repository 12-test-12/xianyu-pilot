// Isolated production-bundle regression: static HTTP only, mocked APIs, no real account data.
const { chromium } = require('../../apps/crawler/node_modules/playwright');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const projectRoot = path.resolve(__dirname, '../..');
process.chdir(projectRoot);
const root = path.join(projectRoot, 'apps/web/dist');
fs.mkdirSync('reports', {recursive:true});
const server = http.createServer((req, res) => {
  const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
  const file = path.resolve(root, '.' + (pathname === '/' ? '/index.html' : pathname));
  if (!file.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  fs.readFile(file, (err, data) => {
    if (err) { res.writeHead(404).end(); return; }
    const type = { '.js':'application/javascript', '.css':'text/css', '.html':'text/html', '.svg':'image/svg+xml', '.png':'image/png', '.ico':'image/x-icon' }[path.extname(file)] || 'application/octet-stream';
    res.writeHead(200, {'Content-Type': type}); res.end(data);
  });
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({channel:'msedge', headless:true});
  try {
    const page = await browser.newPage({ viewport:{width:1440,height:1000} });
    const errors = [], requests = [], checks = [];
    let generation = 0, status = 'pending', generationDelay = 0, accountDelay = 0;
    const account = {id:42,nickname:'UI regression account',externalUid:'test-uid',status:1,cookieStatus:1,authUsable:true,loginStatusCode:'OK'};
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      sessionStorage.setItem('xianyu_auth_token','isolated-test-token');
      window.EventSource = class { constructor() {} close() {} };
    });
    await page.route('**/api/**', async route => {
      const endpoint = new URL(route.request().url()).pathname.slice(4);
      requests.push(endpoint);
      let data = {};
      if (endpoint === '/system/currentUser') data = {username:'UI Test'};
      else if (endpoint === '/system/open-source-config') data = {};
      else if (endpoint === '/xianyu/accounts') {
        if (accountDelay) await new Promise(r=>setTimeout(r,accountDelay));
        data = {records:[account], total:1};
      } else if (endpoint === '/websocket/status') data = {connected:false};
      else if (endpoint === '/captcha/solve-records') data = {list:[]};
      else if (endpoint === '/sse/ticket') data = {ticket:'test-ticket'};
      else if (endpoint === '/qrlogin/generate') {
        generation++;
        if (generationDelay) await new Promise(r=>setTimeout(r,generationDelay));
        data = {sessionId:'qr-'+generation, qrUrl:'data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><rect width="200" height="200" fill="white"/><path d="M10 10h50v50H10zm80 0h50v50H90zm0 80h50v50H90z"/></svg>')};
      } else if (endpoint.startsWith('/qrlogin/status/')) data = {status, ...(status==='confirmed'?{accountId:42}: {})};
      else if (endpoint.endsWith('/refresh-profile')) data = {...account,displayName:'Refreshed profile'};
      await route.fulfill({json:{code:200,data}});
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/#/accounts`);
    await page.locator('.account-selector').first().waitFor();
    await page.locator('.head-actions button').filter({hasText:'扫码'}).click();
    await page.locator('.qr-box img').waitFor();
    const previous = await page.locator('.qr-box img').getAttribute('src');
    generationDelay = 500;
    await page.locator('.scan-modal .inline-link').click();
    assert.equal(await page.locator('.qr-box img').getAttribute('src'), previous);
    assert.equal(await page.locator('.scan-modal .inline-link').isDisabled(), true);
    await page.waitForTimeout(600);
    checks.push('QR refresh keeps the image and disables duplicate refresh');
    generationDelay = 0;
    const beforeSse = requests.filter(x=>x==='/xianyu/accounts').length;
    await page.evaluate(()=>window.dispatchEvent(new CustomEvent('xya-sse-event',{detail:{type:'account_added',accountId:42}})));
    await page.waitForTimeout(150);
    status = 'confirmed';
    await page.locator('.modal-mask').waitFor({state:'hidden',timeout:5000});
    assert.equal(requests.filter(x=>x==='/xianyu/accounts').length-beforeSse, 1);
    checks.push('SSE before QR confirmation closes the modal and refreshes the list once');
    await page.waitForTimeout(250);
    // Profile completion must retain the same account row DOM.
    const row = page.locator('.account-selector').first();
    await row.evaluate(el=>{el.dataset.regressionIdentity='retained'});
    await page.locator('.diagnosis-actions').getByRole('button',{name:'刷新资料',exact:true}).click();
    await page.waitForTimeout(150);
    assert.equal(await row.getAttribute('data-regression-identity'),'retained');
    checks.push('Profile update retains the row DOM');
    // The list refresh status must never shift its own content area.
    const yBefore = await row.evaluate(el=>el.getBoundingClientRect().top);
    accountDelay = 600;
    await page.locator('.toolbar').getByRole('button',{name:'刷新',exact:true}).click();
    await page.waitForTimeout(380);
    const yDuring = await row.evaluate(el=>el.getBoundingClientRect().top);
    assert.equal(yDuring,yBefore);
    await page.waitForTimeout(350);
    checks.push('Slow list refresh leaves the account row at the same vertical position');
    accountDelay = 0;
    status = 'pending'; generationDelay = 600;
    await page.locator('.head-actions button').filter({hasText:'扫码'}).click();
    await page.locator('.scan-modal').waitFor();
    await page.locator('.scan-modal .modal-close').click();
    await page.waitForTimeout(800);
    assert.equal(await page.locator('.modal-mask').count(),0);
    checks.push('Closing during QR generation does not reopen the modal');
    // Repeated login to the same account is independent of the recent SSE cache.
    generationDelay = 0; status = 'confirmed';
    await page.locator('.diagnosis-actions').getByRole('button',{name:'重新扫码',exact:true}).click();
    await page.locator('.qr-box img').waitFor();
    await page.locator('.modal-mask').waitFor({state:'hidden',timeout:5000});
    checks.push('Rescanning the same account still completes within the deduplication window');
    // A delayed destination module must not unmount the visible page, and an
    // intervening navigation back to it must invalidate the delayed result.
    let releaseCode;
    const codeGate = new Promise(resolve=>{releaseCode=resolve});
    await page.route('**/assets/RatesPage-*.js',async route=>{await codeGate;await route.continue()});
    await page.locator('.sidebar').getByRole('button',{name:'评价管理',exact:true}).click();
    await page.waitForTimeout(500);
    assert.equal(await page.locator('.account-selector').count(),1);
    await page.locator('.sidebar').getByRole('button',{name:'闲鱼账号',exact:true}).click();
    releaseCode();
    await page.waitForTimeout(500);
    assert.equal(new URL(page.url()).hash,'#/accounts');
    assert.equal(await page.locator('.account-selector').count(),1);
    checks.push('Delayed page code retains the visible page and cannot override a newer navigation');
    await page.screenshot({path:'reports/flicker-review-accounts.png',fullPage:true});
    assert.deepEqual(errors,[]);
    const result={checks,errors,requestCount:requests.length};
    fs.writeFileSync('reports/flicker-review-browser.json',JSON.stringify(result,null,2));
    console.log(JSON.stringify(result));
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1}).finally(()=>server.close());
