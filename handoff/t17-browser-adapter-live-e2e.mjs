import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

// Repeatable T17 live adapter check; browser and API test data stay temporary.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const nodeModules = 'C:\\Users\\Adam\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\node\\node_modules';
const { chromium } = createRequire(import.meta.url)(path.join(nodeModules, 'playwright'));
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 't17-playwright-edge-'));
const extension = path.join(temp, 'extension');
const positiveExtension = path.join(temp, 'extension-with-screenshot-host-permission');
const deniedProfile = path.join(temp, 'profile-denied');
const positiveProfile = path.join(temp, 'profile-positive');
fs.mkdirSync(extension);
for (const file of ['background.js', 'capture.js', 'manifest.json']) {
  fs.copyFileSync(path.join(root, 'browser_bridge', file), path.join(extension, file));
}

const state = { scenario: 'success', calls: [], stageEntered: null, releaseStage: null };
const server = http.createServer(async (req, res) => {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const payload = chunks.length ? JSON.parse(Buffer.concat(chunks).toString()) : {};
  const call = { path: req.url, payload, scenario: state.scenario };
  state.calls.push(call);
  const respond = (status, value) => {
    const body = JSON.stringify(value);
    res.writeHead(status, { 'content-type': 'application/json', 'content-length': Buffer.byteLength(body) });
    res.end(body);
  };
  if (req.method === 'GET' && (req.url === '/page' || req.url === '/changed')) {
    const body = `<!doctype html><title>T17 controlled</title><main id="root"><h1>${req.url}</h1><button id="save">Save</button></main>`;
    res.writeHead(200, { 'content-type': 'text/html', 'content-length': Buffer.byteLength(body) });
    res.end(body);
    return;
  }
  if (req.url.endsWith('/capability')) return respond(200, { success: true, capability: 'fake-capability' });
  if (req.url.endsWith('/stage')) {
    state.stageEntered?.();
    if (state.scenario === 'navigate') await new Promise((resolve) => { state.releaseStage = resolve; });
    return respond(200, { success: true, staged: true });
  }
  if (req.url.endsWith('/commit')) {
    const attempts = state.calls.filter((item) => item.scenario === state.scenario && item.path.endsWith('/commit')).length;
    if (state.scenario === 'replay' && attempts === 1) return respond(503, { success: false, error_code: 'temporary' });
    if (state.scenario === 'expiry') return respond(410, { success: false, error_code: 'capture_expired' });
    return respond(200, { success: true, request_id: payload.request_id, bundle_artifact_id: 'fake-bundle' });
  }
  if (req.url.endsWith('/abandon')) return respond(200, { success: true });
  if (req.url.endsWith('/capture')) return respond(200, { success: false, error_code: payload.capture_error || 'abandoned' });
  return respond(404, { success: false, error_code: 'not_found' });
});

let context;
try {
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  const manifestPath = path.join(extension, 'manifest.json');
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  manifest.host_permissions = [`http://127.0.0.1:${port}/*`];
  fs.writeFileSync(manifestPath, JSON.stringify(manifest));
  const backgroundPath = path.join(extension, 'background.js');
  const background = fs.readFileSync(backgroundPath, 'utf8').replace(
    'const HUB_URL = "http://127.0.0.1:11435";',
    `const HUB_URL = "http://127.0.0.1:${port}";`,
  );
  fs.writeFileSync(backgroundPath, background);

  fs.cpSync(extension, positiveExtension, { recursive: true });
  const positiveManifestPath = path.join(positiveExtension, 'manifest.json');
  const positiveManifest = JSON.parse(fs.readFileSync(positiveManifestPath, 'utf8'));
  positiveManifest.host_permissions.push('<all_urls>');
  fs.writeFileSync(positiveManifestPath, JSON.stringify(positiveManifest));

  const launchContext = async (userDataDir, extensionPath) => chromium.launchPersistentContext(userDataDir, {
    executablePath: 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    headless: true,
    args: [`--disable-extensions-except=${extensionPath}`, `--load-extension=${extensionPath}`],
  });
  const waitForCaptureListener = async (serviceWorker) => {
    for (let attempt = 0; attempt < 100; attempt++) {
      const ready = await serviceWorker.evaluate(async () => {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        return await chrome.tabs.sendMessage(tab.id, { type: 'LOCAL_AI_VERIFY_CURRENT_TAB' })
          .then((value) => value?.success === true)
          .catch(() => false);
      });
      if (ready) return;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    throw new Error('capture content-script listener did not become ready');
  };
  context = await launchContext(deniedProfile, extension);
  let page = context.pages()[0] ?? await context.newPage();
  await page.goto(`http://127.0.0.1:${port}/page`);
  let worker = context.serviceWorkers()[0] ?? await context.waitForEvent('serviceworker', { timeout: 10000 });
  const expression = async () => {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    return await captureCurrentTab(tab);
  };
  state.scenario = 'privacy_denied';
  const denied = await worker.evaluate(expression);
  const deniedCalls = state.calls.filter((item) => item.scenario === 'privacy_denied');
  const deniedCapture = deniedCalls.find((item) => item.path.endsWith('/capture'))?.payload;
  if (denied?.success !== false || denied?.error_code !== 'permission_denied'
    || deniedCalls.some((item) => item.path.endsWith('/stage') || item.path.endsWith('/commit'))
    || !deniedCapture || deniedCapture.capture_error !== 'permission_denied'
    || 'screenshot' in deniedCapture || 'dom' in deniedCapture || 'html' in deniedCapture) {
    throw new Error(`negative capture/privacy acceptance failed: ${JSON.stringify({ denied, deniedCalls })}`);
  }

  await context.close();
  context = await launchContext(positiveProfile, positiveExtension);
  page = context.pages()[0] ?? await context.newPage();
  await page.goto(`http://127.0.0.1:${port}/page`);
  worker = context.serviceWorkers()[0] ?? await context.waitForEvent('serviceworker', { timeout: 10000 });
  await waitForCaptureListener(worker);
  let runCount = 0;
  const run = async (scenario) => {
    if (runCount++ > 0) await new Promise((resolve) => setTimeout(resolve, 800));
    state.scenario = scenario;
    state.stageEntered = null;
    state.releaseStage = null;
    return await worker.evaluate(expression);
  };

  const success = await run('success');
  if (!success?.success) {
    const diagnostic = await worker.evaluate(async () => {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      const message = await chrome.tabs.sendMessage(tab.id, { type: 'LOCAL_AI_CAPTURE_CURRENT_TAB' }).catch((error) => ({ error: error.message }));
      const screenshot = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' }).then((value) => ({ ok: true, bytes: value.length })).catch((error) => ({ error: error.message }));
      return { tab: { id: tab.id, windowId: tab.windowId, url: tab.url }, message, screenshot };
    });
    throw new Error(`success lifecycle failed: ${JSON.stringify({ success, diagnostic, calls: state.calls.map(({ path, scenario, payload }) => ({ path, scenario, capture_error: payload.capture_error })) })}`);
  }
  const replay = await run('replay');
  if (!replay?.success) throw new Error(`replay lifecycle failed: ${JSON.stringify(replay)}`);
  const replayIds = state.calls.filter((item) => item.scenario === 'replay' && item.path.endsWith('/commit')).map((item) => item.payload.request_id);
  if (replayIds.length !== 2 || replayIds[0] !== replayIds[1]) throw new Error(`replay IDs differ: ${JSON.stringify(replayIds)}`);
  const expired = await run('expiry');
  if (expired?.success !== false || expired?.error_code !== 'capture_expired') throw new Error(`expiry lifecycle failed: ${JSON.stringify({ expired, calls: state.calls.filter((item) => item.scenario === 'expiry').map(({ path, payload }) => ({ path, capture_error: payload.capture_error })) })}`);

  await page.goto(`http://127.0.0.1:${port}/page`);
  await new Promise((resolve) => setTimeout(resolve, 800));
  state.scenario = 'navigate';
  const stageReached = new Promise((resolve) => { state.stageEntered = resolve; });
  const pending = worker.evaluate(expression);
  await Promise.race([stageReached, new Promise((_, reject) => setTimeout(() => reject(new Error('stage request not reached')), 8000))]);
  await page.goto(`http://127.0.0.1:${port}/changed`);
  await new Promise((resolve) => setTimeout(resolve, 250));
  for (let i = 0; !state.releaseStage && i < 50; i++) await new Promise((resolve) => setTimeout(resolve, 20));
  state.releaseStage?.();
  const navigated = await pending;
  const navCommits = state.calls.filter((item) => item.scenario === 'navigate' && item.path.endsWith('/commit'));
  const navAbandons = state.calls.filter((item) => item.scenario === 'navigate' && item.path.endsWith('/abandon'));
  if (navigated?.success !== false || navigated?.error_code !== 'target_changed' || navCommits.length || navAbandons.length !== 1) {
    throw new Error(`navigation lifecycle failed: ${JSON.stringify({ navigated, navCommits: navCommits.length, navAbandons: navAbandons.length })}`);
  }
  console.log(JSON.stringify({ status: 'PASS', browser: 'bundled Playwright + isolated headless Edge', adapter: 'candidate background.js/capture.js; temporary fake API URL and host permissions only', scenarios: ['no screenshot permission => permission_denied without stage/commit or DOM/screenshot payload', 'stage/commit success', 'lost-response replay with same request_id', 'expired commit rejection', 'navigation after stage abandons without commit'], results: [denied, success, replay, expired, navigated], replay_request_ids: replayIds }));
} finally {
  await context?.close().catch(() => {});
  await new Promise((resolve) => server.close(resolve));
  if (path.resolve(temp).startsWith(path.resolve(os.tmpdir()) + path.sep)) fs.rmSync(temp, { recursive: true, force: true });
}
