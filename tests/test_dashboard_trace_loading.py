"""Exercise the shipped trace selector and detail polling against failed HTTP reads."""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from local_ai_hub.dashboard import DASHBOARD_HTML
from local_ai_hub.process_utils import hidden_run_kwargs


def _trace_scenario(scenario: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise trace detail loading")
    start = DASHBOARD_HTML.index("async function openTrace(id)")
    helper = DASHBOARD_HTML.find("function renderTraceLoadState(")
    source = DASHBOARD_HTML[helper:start] if helper >= 0 else ""
    source += DASHBOARD_HTML[start:DASHBOARD_HTML.index("function openModal(", start)]
    harness = r"""
const assert=require('node:assert/strict');
const body={innerHTML:'Previous trace contents',className:'trace-page-body',
  insertAdjacentHTML(position,html){this.innerHTML=html+this.innerHTML}};
const nodes={tracePageBody:body,tracePageTitle:{},tracePageLive:{}};
const $=id=>id==='traceLoadState'&&body.innerHTML.includes('id="traceLoadState"')
  ?{remove(){body.innerHTML=body.innerHTML.replace(/<section[^>]*id="traceLoadState"[\s\S]*?<\/section>/,'')}}
  :nodes[id]||null;
const esc=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
let activeTraceId='',tracePollGeneration=0,traceSeq=0,traceEvents=[],traceEventTotal=0,
  traceOpenSteps=new Set(),traceView='',activeTraceData=null,traceOptionalDetailsOpen=false,
  traceDetailPoller=null,tracePollAbortController=null,lastTraces=[],renders=0;
let response={ok:false,status:503,payload:{success:false,retryable:true,
  mode:'gaming',error_code:'operational_mode_blocked',error:'hub paused: gaming mode active'}};
let pendingFetch=null;
const requests=[],pollers=[];
async function apiFetch(url){requests.push(url);if(pendingFetch)return pendingFetch;
  if(response.error)throw response.error;
  return {ok:response.ok,status:response.status,json:async()=>{
    if(response.jsonError)throw response.jsonError;return response.payload}}}
function renderTraceList(){}
function switchTab(page){assert.equal(page,'traceInspector')}
function openModal(){assert.fail('A trace loading error belongs in the detail pane')}
function createDashboardStatusPoller(poll){const p={poll,stopped:false,start(){},stop(){this.stopped=true}};pollers.push(p);return p}
function traceFiniteSequence(value,prior){return Number.isFinite(value)?value:prior}
function traceAppendEvents(events,next,total){return {events:[...events,...next],eventsTotal:total}}
function renderTraceDetail(data){renders++;activeTraceData=data;body.innerHTML='Loaded '+data.session.id}
async function fetchPrimaryTraceContent(id,base){return base}
async function fetchTraceMetrics(){return null}
const success=id=>({ok:true,status:200,payload:{success:true,terminal:false,state:'running',
  next_seq:1,events_total:1,events:[],session:{id}}});
"""
    script = harness + source + "\n(async()=>{\n" + scenario + "\n})().catch(e=>{console.error(e);process.exitCode=1});"
    result = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, timeout=8,
        **hidden_run_kwargs(),
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_selected_trace_replaces_initial_or_previous_content_while_loading():
    _trace_scenario("""
await openTrace('selected');
assert.match(body.innerHTML,/Loading trace/);
assert.doesNotMatch(body.innerHTML,/Previous trace|Choose a trace/);
assert.match(body.innerHTML,/role="status"/);
""")


def test_gaming_rejection_is_visible_in_detail_and_remains_retryable():
    _trace_scenario("""
await openTrace('paused');await pollers[0].poll(()=>true);
assert.match(body.innerHTML,/Trace loading paused/);
assert.match(body.innerHTML,/gaming mode active/);
assert.match(body.innerHTML,/retry/i);
assert.doesNotMatch(body.innerHTML,/Choose a trace|live ·/);
assert.equal(pollers[0].stopped,false);
""")


@pytest.mark.parametrize("failure", [
    {"ok": False, "status": 503, "payload": {"success": False, "retryable": True, "error": "temporary <failure>"}},
    {"ok": False, "status": 500, "payload": {"success": True}},
    {"ok": True, "status": 200, "payload": {"success": False, "error": "read refused"}},
])
def test_http_and_business_failures_never_look_like_loaded_traces(failure):
    _trace_scenario(f"""
response={json.dumps(failure)};
await openTrace('failed');await pollers[0].poll(()=>true);
assert.match(body.innerHTML,/Trace unavailable/);
assert.equal(renders,0);
assert.doesNotMatch(body.innerHTML,/<failure>/);
if(response.payload.retryable!==true)assert.equal(pollers[0].stopped,true);
""")


@pytest.mark.parametrize("failure", ["error:Error('network lost')", "jsonError:Error('invalid JSON')"])
def test_network_and_invalid_json_failures_are_visible(failure):
    _trace_scenario(f"""
response={{{failure}}};
await openTrace('failed');await pollers[0].poll(()=>true);
assert.match(body.innerHTML,/Trace unavailable/);
assert.match(body.innerHTML,/{'network lost' if failure.startswith('error:') else 'invalid JSON'}/);
assert.equal(pollers[0].stopped,false);
""")


def test_failure_retains_loaded_detail_and_identical_success_clears_error():
    _trace_scenario("""
response=success('same');await openTrace('same');await pollers[0].poll(()=>true);
assert.equal(body.innerHTML,'Loaded same');
response={error:Error('network lost')};await pollers[0].poll(()=>true);
assert.match(body.innerHTML,/Loaded same/);
assert.match(body.innerHTML,/last loaded details/);
assert.match(body.innerHTML,/network lost/);
response=success('same');await pollers[0].poll(()=>true);
assert.equal(body.innerHTML,'Loaded same');assert.equal(renders,2);
""")


def test_late_failure_from_previous_selection_cannot_replace_current_trace():
    _trace_scenario("""
await openTrace('old');let resolveOld;
pendingFetch=new Promise(resolve=>{resolveOld=resolve});
const oldPoll=pollers[0].poll(()=>true);
pendingFetch=null;response=success('new');await openTrace('new');
await pollers[1].poll(()=>true);assert.equal(body.innerHTML,'Loaded new');
resolveOld({ok:false,status:503,json:async()=>({success:false,retryable:true,error:'old failure'})});
await oldPoll;assert.equal(body.innerHTML,'Loaded new');
assert.equal(pollers[0].stopped,true);
""")
