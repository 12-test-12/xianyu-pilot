// Production UI regression with isolated storage and mocked APIs.
const { chromium } = require('../../apps/crawler/node_modules/playwright');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../../apps/web/dist');
const reportDir = path.resolve(__dirname, '../../reports');
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  const file = path.resolve(root, '.' + (url.pathname === '/' ? '/index.html' : decodeURIComponent(url.pathname)));
  if (!file.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  fs.readFile(file, (error, data) => {
    if (error) { res.writeHead(404).end(); return; }
    if (url.searchParams.has('desktop') && file.endsWith('index.html')) {
      data = data.toString().replace('<head>', '<head><meta name="xianyu-desktop-bootstrap" content="test-bootstrap">');
    }
    const type = { '.js': 'application/javascript', '.css': 'text/css', '.html': 'text/html', '.svg': 'image/svg+xml', '.png': 'image/png' }[path.extname(file)];
    res.writeHead(200, { 'Content-Type': type || 'application/octet-stream' }).end(data);
  });
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const checks = [], errors = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1180, height: 820 } });
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      sessionStorage.setItem('xianyu_auth_token', 'isolated-test-token');
      window.EventSource = class { close() {} };
    });
    await page.route('**/api/**', route => {
      const endpoint = new URL(route.request().url()).pathname.slice(4);
      let data = {};
      if (endpoint === '/desktop/session') data = { token: 'isolated-desktop-token', username: 'UI Test' };
      else if (endpoint === '/system/currentUser') data = { username: 'UI Test' };
      else if (endpoint === '/sse/ticket') data = { ticket: 'test-ticket' };
      else if (endpoint === '/xianyu/accounts') data = { records: [], total: 0 };
      return route.fulfill({ json: { code: 200, data } });
    });
    const base = `http://127.0.0.1:${server.address().port}`;
    fs.mkdirSync(reportDir, { recursive: true });
    await page.goto(`${base}/?desktop=1#/accounts`);
    await page.locator('.page-viewport .wide-right').waitFor();
    await page.locator('.sidebar').evaluate(el => { el.dataset.identity = 'retained'; });
    for (const width of [900, 780, 1180]) {
      await page.setViewportSize({ width, height: 820 });
      await page.waitForTimeout(350);
      const sidebar = await page.locator('.sidebar').evaluateAll(elements => {
        const el = elements[0];
        return el && { x: el.getBoundingClientRect().x, identity: el.dataset.identity };
      });
      assert.deepEqual(sidebar, { x: 0, identity: 'retained' }, `desktop sidebar at width ${width}`);
      assert.equal(await page.locator('.topbar').isVisible(), true);
      assert.equal(await page.locator('.main').evaluate(el => el.getBoundingClientRect().x),
        await page.locator('.sidebar').evaluate(el => el.getBoundingClientRect().width));
      await page.locator('.sidebar .nav-item').filter({ hasText: '连接管理' }).click();
      await page.waitForFunction(() => location.hash === '#/connections');
      await page.locator('.page-viewport > *').first().waitFor();
      assert.equal(await page.locator('.sidebar').getAttribute('data-identity'), 'retained');
      if (width === 780) await page.screenshot({ path: path.join(reportDir, 'navigation-desktop-narrow.png') });
    }
    checks.push('Desktop sidebar survives resizing across 900px and page navigation');

    let releaseCode, codeRequested;
    const codeGate = new Promise(resolve => { releaseCode = resolve; });
    const codeStarted = new Promise(resolve => { codeRequested = resolve; });
    await page.route('**/assets/ModelSettingsPage-*.js', async route => {
      codeRequested();
      await codeGate;
      await route.continue();
    });
    await page.locator('.sidebar .nav-item').filter({ hasText: '系统设置' }).click();
    await page.locator('.system-settings-page').waitFor();
    await page.locator('.system-settings-page').evaluate(el => { el.dataset.identity = 'retained'; });
    await page.locator('.config-link').filter({ hasText: '模型配置' }).click();
    await codeStarted;
    await page.waitForTimeout(500);
    assert.equal(await page.locator('.system-settings-page').getAttribute('data-identity'), 'retained');
    assert.equal(new URL(page.url()).hash, '#/settings-system');
    await page.locator('.config-link').filter({ hasText: '系统配置' }).click();
    releaseCode();
    await page.waitForTimeout(350);
    assert.equal(new URL(page.url()).hash, '#/settings-system');
    await page.locator('.config-link').filter({ hasText: '模型配置' }).click();
    await page.locator('.model-settings-page').waitFor();
    checks.push('Slow settings code retains the visible page and respects a newer navigation');

    await page.evaluate(() => {
      window.navigationFrames = { blank: 0, hidden: 0, samples: 0, running: true };
      function sample() {
        const state = window.navigationFrames;
        if (!state.running) return;
        state.samples++;
        const children = [...document.querySelectorAll('.page-viewport > *, .settings-main > *')];
        if (!children.length || document.querySelector('.settings-main')?.childElementCount === 0) state.blank++;
        if (children.some(el => Number(getComputedStyle(el).opacity) === 0)) state.hidden++;
        requestAnimationFrame(sample);
      }
      requestAnimationFrame(sample);
    });
    for (const route of ['settings-system', 'settings-model', 'settings-embedding', 'connections', 'accounts', 'logs', 'accounts']) {
      await page.evaluate(key => {
        // Use rendered controls so navigation guards and prefetch run normally.
        const button = [...document.querySelectorAll('.nav-item, .config-link')].find(el => el.classList.contains('config-link')
          ? ({ 'settings-system': '系统配置', 'settings-model': '模型配置', 'settings-embedding': '向量模型' }[key] === el.textContent.trim())
          : el.textContent.trim() === ({ connections: '连接管理', accounts: '闲鱼账号', logs: '操作日志' }[key]));
        if (!button) throw new Error(`Missing navigation for ${key}`);
        button.click();
      }, route);
      await page.waitForTimeout(45);
    }
    await page.waitForTimeout(500);
    const frames = await page.evaluate(() => { window.navigationFrames.running = false; return window.navigationFrames; });
    assert.equal(frames.blank, 0, JSON.stringify(frames));
    assert.equal(frames.hidden, 0, JSON.stringify(frames));
    checks.push('Rapid page and settings navigation has no empty or transparent frames');

    let releaseInitialCode;
    const initialCodeGate = new Promise(resolve => { releaseInitialCode = resolve; });
    await page.route('**/assets/RatesPage-*.js', async route => { await initialCodeGate; await route.continue(); });
    await page.goto(`${base}/?desktop=1&initial=1#/rates`, { waitUntil: 'domcontentloaded' });
    await page.locator('.page-skeleton-placeholder').waitFor();
    assert.equal(await page.locator('.sidebar').isVisible(), true);
    releaseInitialCode();
    await page.locator('.page-skeleton-placeholder').waitFor({ state: 'hidden' });
    checks.push('A slow initial route shows a loading placeholder and keeps navigation available');

    await page.goto(`${base}/#/accounts`);
    await page.locator('.page-viewport .wide-right').waitFor();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('.mobile-shell').waitFor();
    checks.push('Regular mobile browser retains its mobile layout');
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(reportDir, 'navigation-browser.json'), JSON.stringify({ checks, frames, errors }, null, 2));
    console.log(JSON.stringify({ checks, frames, errors }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => server.close());
