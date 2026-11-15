"""Exercise actual dashboard JavaScript against the backend's wire DTOs."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_dashboard_consumes_real_model_and_telemetry_payloads():
    app_js = Path(__file__).resolve().parents[1] / "src/local_ai_hub/ui_static/app.js"
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const elements = new Map();
const calls = [];
const requests = [];
function node(id = '') {
  return {
    id, textContent: '', value: '', children: [], attrs: {},
    classList: { add() {}, remove() {}, toggle() { return false; } },
    append(...children) { this.children.push(...children); },
    prepend(...children) { this.children.unshift(...children); },
    replaceChildren(...children) { this.children = [...children]; },
    addEventListener() {},
    removeAttribute(name) { delete this.attrs[name]; },
    setAttribute(name, value) { this.attrs[name] = value; },
    getAttribute(name) { return this.attrs[name] || null; },
  };
}
function byId(id) {
  if (!elements.has(id)) elements.set(id, node(id));
  return elements.get(id);
}
const document = {
  hidden: false,
  getElementById: byId,
  querySelectorAll() { return []; },
  addEventListener() {},
  createElement: (tag) => node(tag),
  createDocumentFragment: () => node('fragment'),
};
const pages = [
  {timeline: [
     {id: 11, timestamp: 1700000000, event_type: 'newer', action: 'run', duration_ms: 0, net_tokens_saved: 12, success: true},
     {id: 12, timestamp: 1700000010, event_type: 'newest', action: 'run', duration_ms: 4, net_tokens_saved: 6, success: true},
   ], next_cursor: 11, has_more: true, success: true},
  {timeline: [
     {id: 9, timestamp: 1699999900, event_type: 'older', action: 'run', duration_ms: 1, net_tokens_saved: 0, success: true},
  ], next_cursor: null, has_more: false, success: true},
];
function response(data, status = 200) {
  return {ok: status < 400, status,
    headers: {get() { return 'application/json'; }},
    async json() { return data; },
  };
}
async function fetch(url, options) {
  calls.push(url);
  requests.push({url, options});
  if (url === '/api/models')
    return response({object: 'list', data: [{id: 'qwen3.5:9b', object: 'model', owned_by: 'ollama'}]});
  if (url.startsWith('/api/telemetry/timeline'))
    return response(url.includes('before_id=11') ? pages[1] : pages[0]);
  if (url === '/ready') return response({success:true, ready:true});
  if (url.startsWith('/api/preprocess/status?')) return response({success:true, root:'/tmp/repo', phase:'files'});
  if (url === '/api/preprocess') return response({success:true, root:'/tmp/repo', phase:'files'});
  return response({success:false, error:'intentional'});
}
const context = {document, window:{addEventListener(){}}, fetch, URLSearchParams, AbortController,
  setTimeout() { return 1; }, clearTimeout() {}, console, Date};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
function text(el) {
  return el.textContent + el.children.map(text).join(' ');
}
(async () => {
  context.setSection('models');
  await context.loadModels();
  assert.match(text(byId('model-list')), /qwen3\.5:9b/);
  assert.match(byId('models-status').textContent, /1 installed/);

  context.setSection('diagnostics');
  await context.loadTelemetryTimeline(false);
  assert.match(text(byId('telemetry-timeline')), /newer/);
  assert.equal(byId('load-older-telemetry').disabled, false);
  await context.loadTelemetryTimeline(true);
  const combined = text(byId('telemetry-timeline'));
  assert.ok(combined.indexOf('older') < combined.indexOf('newer'));
  assert.ok(calls.some(url => url.includes('before_id=11')));
  assert.equal(byId('load-older-telemetry').disabled, true);

  byId('project-root').value = '/tmp/repo';
  context.setSection('projects');
  await context.handleProjectAction('check');
  await context.handleProjectAction('reindex');
  await context.handleProjectAction('unregister');
  const projectRequests = requests.filter(row => row.url.includes('/api/preprocess'));
  assert.equal(projectRequests.length, 3);
  assert.equal(projectRequests[0].options.method, 'GET');
  assert.match(projectRequests[0].url, /root=%2Ftmp%2Frepo/);
  assert.equal(JSON.parse(projectRequests[1].options.body).action, 'refresh');
  assert.equal(JSON.parse(projectRequests[2].options.body).action, 'unregister');
  assert.equal(JSON.parse(projectRequests[2].options.body).purge_data, false);

  const failure = await context.request('/invalid');
  assert.equal(failure.ok, false);
})().catch(err => { console.error(err); process.exitCode = 1; });
"""
    proc = subprocess.run(
        ["node", "-e", script, str(app_js)],
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
