import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const handler = process.env.T17_HANDLER_URL;
if (!handler) throw new Error('T17_HANDLER_URL is required');
const nodeModules = 'C:\\Users\\Adam\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\node\\node_modules';
const { chromium } = createRequire(import.meta.url)(path.join(nodeModules, 'playwright'));
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 't17-real-handler-edge-'));
const deniedExt = path.join(temp, 'extension-active-tab-only');
const positiveExt = path.join(temp, 'extension-screenshot-permission');
const deniedProfile = path.join(temp, 'profile-denied');
const positiveProfile = path.join(temp, 'profile-positive');
for (const dir of [deniedExt, positiveExt]) fs.mkdirSync(dir);
const state = { calls: [] };
const api = http.createServer(async (req, res) => {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const raw = Buffer.concat(chunks);
  const origin = req.headers.origin || '';
  let payload = {};
  try { payload = raw.length ? JSON.parse(raw.toString('utf8')) : {}; } catch {}
  state.calls.push({path: req.url, origin, method: req.method, capture_error: payload.capture_error || null,
    has_screenshot: Object.hasOwn(payload, 'screenshot'), has_dom: Object.hasOwn(payload, 'dom'),
    url: payload.url || null, target_origin: payload.target_origin || null});
  try {
    const response = await fetch(`${handler}${req.url}`, {
      method: req.method,
      headers: {'content-type': 'application/json', 'origin': origin, 'x-localai-tenant': 't17-browser-e2e'},
      body: raw.length ? raw : undefined,
    });
    const body = Buffer.from(await response.arrayBuffer());
    res.writeHead(response.status, {'content-type': response.headers.get('content-type') || 'application/json', 'content-length': body.length});
    res.end(body);
  } catch (error) {
    res.writeHead(502, {'content-type': 'application/json'});
    res.end(JSON.stringify({success:false,error_code:'registered_handler_unavailable',message:String(error)}));
  }
});
const pageServer = http.createServer((req, res) => {
  if (req.method !== 'GET' || !['/page'].includes(new URL(req.url, 'http://local').pathname)) {
    res.writeHead(404); res.end(); return;
  }
  const body = '<!doctype html><title>T17 isolated fixture</title><main><h1>Fixture checkout</h1><button id="save">Save</button></main>';
  res.writeHead(200, {'content-type':'text/html','content-length':Buffer.byteLength(body)}); res.end(body);
});
let context;
try {
  await new Promise(resolve => api.listen(0, '127.0.0.1', resolve));
  await new Promise(resolve => pageServer.listen(0, '127.0.0.1', resolve));
  const apiPort = api.address().port;
  const pageUrl = `http://127.0.0.1:${pageServer.address().port}/page`;
  const apiUrl = `http://127.0.0.1:${apiPort}`;
  for (const dir of [deniedExt, positiveExt]) {
    for (const file of ['background.js','capture.js','manifest.json']) fs.copyFileSync(path.join(root,'browser_bridge',file),path.join(dir,file));
    const manifestFile=path.join(dir,'manifest.json');
    const manifest=JSON.parse(fs.readFileSync(manifestFile,'utf8'));
    manifest.host_permissions=[apiUrl+'/*'];
    fs.writeFileSync(manifestFile,JSON.stringify(manifest));
    const bg=path.join(dir,'background.js');
    fs.writeFileSync(bg,fs.readFileSync(bg,'utf8').replace('const HUB_URL = "http://127.0.0.1:11435";',`const HUB_URL = "${apiUrl}";`));
  }
  const positiveManifest=JSON.parse(fs.readFileSync(path.join(positiveExt,'manifest.json'),'utf8'));
  positiveManifest.host_permissions.push('<all_urls>');
  fs.writeFileSync(path.join(positiveExt,'manifest.json'),JSON.stringify(positiveManifest));
  const launch=async(userDataDir,extensionPath)=>chromium.launchPersistentContext(userDataDir,{
    executablePath:'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',headless:true,
    args:[`--disable-extensions-except=${extensionPath}`,`--load-extension=${extensionPath}`],
  });
  const bindOrigin=async(worker)=>{
    const id=await worker.evaluate(()=>chrome.runtime.id);
    const response=await fetch(`${handler}/_test/origin`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({origin:`chrome-extension://${id}`})});
    if(!response.ok) throw new Error(`handler rejected extension origin: ${response.status}`);
    return id;
  };
  const capture=async(worker)=>worker.evaluate(async()=>{
    const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
    return await captureCurrentTab(tab);
  });
  context=await launch(deniedProfile,deniedExt);
  let page=context.pages()[0]??await context.newPage(); await page.goto(pageUrl);
  let worker=context.serviceWorkers()[0]??await context.waitForEvent('serviceworker',{timeout:10000});
  await bindOrigin(worker);
  const denied=await capture(worker);
  const deniedCalls=state.calls.slice();
  if(denied?.success!==false||denied?.error_code!=='permission_denied'||deniedCalls.length!==0) {
    const diagnostic=await worker.evaluate(async()=>{const [tab]=await chrome.tabs.query({active:true,currentWindow:true});const page=await chrome.tabs.sendMessage(tab.id,{type:'LOCAL_AI_CAPTURE_CURRENT_TAB'}).catch(e=>({error:e.message}));return {tab:{url:tab.url,id:tab.id},page:{success:page.success,url:page.url,target_origin:page.target_origin,capture_identity:page.capture_identity,error_code:page.error_code}};});
    throw new Error(`activeTab-only negative failed: ${JSON.stringify({denied,deniedCalls,diagnostic})}`);
  }
  const negativeStore=await fetch(`${handler}/_test/artifacts`).then(response=>response.json());
  if(!Array.isArray(negativeStore.artifact_ids)||negativeStore.artifact_ids.length!==0)
    throw new Error(`permission-denied path minted artifacts: ${JSON.stringify(negativeStore)}`);
  await context.close(); context=null;
  const beforePositive=state.calls.length;
  context=await launch(positiveProfile,positiveExt);
  page=context.pages()[0]??await context.newPage(); await page.goto(pageUrl);
  worker=context.serviceWorkers()[0]??await context.waitForEvent('serviceworker',{timeout:10000});
  await bindOrigin(worker);
  const positive=await capture(worker);
  const positiveCalls=state.calls.slice(beforePositive);
  if(!positive?.success||!positive.bundle_artifact_id||!positiveCalls.some(c=>c.path.endsWith('/stage'))||!positiveCalls.some(c=>c.path.endsWith('/commit')))
    throw new Error(`real handler stage/commit failed: ${JSON.stringify({positive,positiveCalls})}`);
  console.log('T17_HANDLER_RESULT='+JSON.stringify({negative:denied,positive,negative_artifact_ids:negativeStore.artifact_ids,positive_paths:positiveCalls.map(c=>c.path)}));
} finally {
  if(context) await context.close();
  await new Promise(resolve=>api.close(resolve));
  await new Promise(resolve=>pageServer.close(resolve));
  fs.rmSync(temp,{recursive:true,force:true});
}
