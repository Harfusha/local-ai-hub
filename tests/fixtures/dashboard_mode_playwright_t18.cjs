const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const http = require('node:http');
const { chromium } = require(process.env.T18_PLAYWRIGHT_PACKAGE);

const requests = [];
let html = '';
let currentMode = 'active';
let gamingModePolls = 0;

function respond(res, status, payload, contentType = 'application/json; charset=utf-8') {
  const body = typeof payload === 'string' ? payload : JSON.stringify(payload);
  res.writeHead(status, { 'Content-Type': contentType, 'Cache-Control': 'no-store' });
  res.end(body);
}

function fixtureServer() {
  return http.createServer(async (req, res) => {
    const url = new URL(req.url || '/', 'http://127.0.0.1');
    if (req.method === 'GET' && (url.pathname === '/' || url.pathname === '/dashboard')) {
      respond(res, 200, html, 'text/html; charset=utf-8');
      return;
    }

    const request = { method: req.method, path: url.pathname, token: req.headers['x-localai-token'] || null, client: req.headers['x-localai-client'] || null };
    requests.push(request);

    if (req.method === 'GET' && url.pathname === '/api/mode') {
      if (currentMode === 'gaming') gamingModePolls += 1;
      const unloadPending = currentMode !== 'gaming' || gamingModePolls < 2;
      respond(res, 200, {
        success: true,
        mode: currentMode,
        runtime_unload: unloadPending ? { state: 'pending' } : { state: 'complete', success: true },
      });
      return;
    }
    if (req.method === 'GET' && url.pathname === '/api/live/status') {
      respond(res, 200, {
        success: false,
        hub_online: false,
        status: 'degraded',
        current: { degraded: true, health: 'degraded' },
        error: 'fixture status degraded',
      });
      return;
    }
    if (req.method === 'POST' && url.pathname === '/api/admin/mode') {
      let raw = '';
      for await (const chunk of req) raw += chunk;
      request.body = JSON.parse(raw || '{}');
      // Exercise a rejected response independently of the retired token input UI.
      if (request.body.mode === 'maintenance') {
        respond(res, 401, { success: false, error: 'unauthorized' });
        return;
      }
      if (request.body.mode === 'gaming') {
        currentMode = 'gaming';
        respond(res, 200, {
          success: true,
          mode: 'gaming',
          runtime_unload: { state: 'pending' },
          accelerator_release: { success: false },
          job_cancellation: { success: false },
        });
        return;
      }
      respond(res, 503, { success: false, error: 'fixture mode service unavailable' });
      return;
    }
    respond(res, 200, { success: true, data: [], items: [], events: [], errors: [] });
  });
}

async function main() {
  html = await fs.readFile(process.argv[2], 'utf8');
  const server = fixtureServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  const baseUrl = `http://127.0.0.1:${address.port}`;
  let browser;
  try {
    browser = await chromium.launch({ headless: true, args: ['--disable-gpu'], executablePath: process.env.T18_CHROMIUM_EXECUTABLE });
    const context = await browser.newContext();
    const page = await context.newPage();
    page.setDefaultTimeout(5000);
    const pageErrors = [];
    page.on('pageerror', error => pageErrors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') pageErrors.push(message.text()); });
    page.on('dialog', dialog => dialog.dismiss());
    await page.addInitScript(() => {
      localStorage.removeItem('apiToken');
      sessionStorage.removeItem('localAiHubToken');
    });
    await page.route('**/*', async route => {
      if (new URL(route.request().url()).origin === baseUrl) await route.continue();
      else await route.abort();
    });
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => document.querySelector('#activityModeBadge')?.dataset.mode === 'active', null, { timeout: 8000 });
    try {
    await page.waitForFunction(() => document.querySelector('#overviewHealthLevel')?.textContent.trim() === 'Degraded', null, { timeout: 8000 });
    } catch (error) {
      const conn = await page.locator('#conn').evaluate(el => ({ text: el.textContent.trim(), className: el.className }));
      console.error(JSON.stringify({ requests, conn, pageErrors }));
      throw error;
    }

    const initialModeGet = requests.find(item => item.method === 'GET' && item.path === '/api/mode');
    assert.ok(initialModeGet, 'dashboard must load mode from the loopback read endpoint');
    const initialMode = await page.locator('#activityModeBadge').getAttribute('data-mode');
    const statusPill = await page.locator('#conn').evaluate(el => ({ text: el.textContent.trim(), warning: el.classList.contains('warn-t') }));
    const overviewHealth = await page.locator('#overviewHealthLevel').textContent();
    await page.locator('#controlMenu > summary').click();

    await page.locator('#activityModeGaming').click();
    await page.waitForFunction(() => document.querySelector('#activityModeStatus')?.textContent.includes('accelerator release incomplete'), null, { timeout: 8000 });
    const partial = await page.locator('#activityModeStatus').textContent();
    const modeAfterPartial = await page.locator('#activityModeBadge').getAttribute('data-mode');
    const partialBadgeText = await page.locator('#activityModeBadge').textContent();
    const pressedMode = await page.locator('[data-activity-mode][aria-pressed="true"]').getAttribute('data-activity-mode');
    const buttonsEnabledAfterPartial = await page.locator('[data-activity-mode]').evaluateAll(items => items.every(item => !item.disabled));
    await page.waitForFunction(() => document.querySelector('#activityModeStatus')?.textContent.includes('VRAM unload complete'), null, { timeout: 8000 });
    const completedStatus = await page.locator('#activityModeStatus').textContent();
    const partialPost = requests.find(item => item.method === 'POST' && item.path === '/api/admin/mode' && item.body?.mode === 'gaming');
    assert.ok(partialPost, 'gaming click must POST through dashboard apiFetch');

    await page.locator('#activityModeMaintenance').click();
    await page.waitForFunction(() => document.querySelector('#activityModeStatus')?.textContent.includes('Unauthorized (HTTP 401)'), null, { timeout: 8000 });
    const unauthorizedStatus = await page.locator('#activityModeStatus').textContent();
    const modeAfterUnauthorized = await page.locator('#activityModeBadge').getAttribute('data-mode');
    const unauthorizedPost = requests.find(item => item.method === 'POST' && item.path === '/api/admin/mode' && item.body?.mode === 'maintenance');
    const buttonsEnabledAfterUnauthorized = await page.locator('[data-activity-mode]').evaluateAll(items => items.every(item => !item.disabled));

    await page.locator('#activityModeActive').click();
    await page.waitForFunction(() => document.querySelector('#activityModeStatus')?.textContent.includes('HTTP 503'), null, { timeout: 8000 });
    const serverErrorStatus = await page.locator('#activityModeStatus').textContent();
    const modeAfterServerError = await page.locator('#activityModeBadge').getAttribute('data-mode');
    const serverErrorPost = requests.find(item => item.method === 'POST' && item.path === '/api/admin/mode' && item.body?.mode === 'active');
    const buttonsEnabledAfterServerError = await page.locator('[data-activity-mode]').evaluateAll(items => items.every(item => !item.disabled));

    const receipt = {
      initialMode,
      initialModeGetToken: initialModeGet?.token ?? null,
      statusPill,
      overviewHealth: overviewHealth.trim(),
      partialMode: modeAfterPartial,
      partialBadgeText: partialBadgeText?.trim() ?? '',
      partialToken: partialPost?.token ?? null,
      partialClient: partialPost?.client ?? null,
      partialStatus: partial?.trim() ?? '',
      pressedMode,
      buttonsEnabledAfterPartial,
      completedStatus: completedStatus?.trim() ?? '',
      unauthorizedStatus: unauthorizedStatus?.trim() ?? '',
      modeAfterUnauthorized,
      unauthorizedToken: unauthorizedPost?.token ?? null,
      buttonsEnabledAfterUnauthorized,
      serverErrorStatus: serverErrorStatus?.trim() ?? '',
      modeAfterServerError,
      serverErrorToken: serverErrorPost?.token ?? null,
      buttonsEnabledAfterServerError,
    };
    process.stdout.write(`${JSON.stringify(receipt)}\n`);
    await context.close();
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}

main().catch(error => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
