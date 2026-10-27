"""Page reads must finish with data or an explicit unavailable state."""
from __future__ import annotations

import shutil
import subprocess

import pytest

from local_ai_hub.dashboard import DASHBOARD_HTML
from local_ai_hub.process_utils import hidden_run_kwargs


def _source(start: str, end: str) -> str:
    first = DASHBOARD_HTML.index(start)
    return DASHBOARD_HTML[first:DASHBOARD_HTML.index(end, first)]


def _javascript(source: str, scenario: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise dashboard page reads")
    script = "const assert=require('node:assert/strict');\n" + source
    script += "\n(async()=>{\n" + scenario + "\n})().catch(e=>{console.error(e);process.exitCode=1});"
    result = subprocess.run([node, "-e", script], capture_output=True, text=True,
                            timeout=8, **hidden_run_kwargs())
    assert result.returncode == 0, result.stderr or result.stdout


def _api(scenario: str, extra: str = "") -> None:
    setup = r"""
const timers=[];let sentSignal=null,calls=0,pendingBody=true;
const scopeAgentOsRequest=(path,options)=>({path,options});
const setTimeout=(callback,delay)=>{const timer={callback,delay,canceled:false};timers.push(timer);return timer};
const clearTimeout=timer=>{timer.canceled=true};
const nativeFetch=async(path,options)=>{
  calls++;sentSignal=options.signal;
  return {ok:true,status:200,body:{},json:async()=>{
    if(!pendingBody)return {success:true,config:{hardware:{profile:'cpu'}}};
    return new Promise((resolve,reject)=>{
      const abort=()=>reject(new Error('body aborted'));
      if(options.signal.aborted)abort();else options.signal.addEventListener('abort',abort,{once:true});
    });
  }};
};
"""
    _javascript(setup + _source("async function apiFetch(", "function setFrontendVisionCaptureState(") + extra, scenario)


@pytest.mark.parametrize("with_parent", [False, True])
def test_api_deadline_covers_body_read_with_or_without_parent_signal(with_parent):
    _api(f"""
const parent=new AbortController();
const response=await apiFetch('/api/config',{{timeoutMs:1200,{"signal:parent.signal" if with_parent else ""}}});
assert.equal(timers.length,1);assert.equal(timers[0].canceled,false);
const reading=response.json();timers[0].callback();
await assert.rejects(reading,/timed out/i);
assert.equal(sentSignal.aborted,true);assert.equal(timers[0].canceled,true);
assert.equal(parent.signal.aborted,false);
""")


def test_parent_cancellation_is_preserved_during_body_read():
    _api("""
const parent=new AbortController();
const response=await apiFetch('/api/config',{signal:parent.signal});
const reading=response.json();parent.abort();
await assert.rejects(reading,/body aborted/);
assert.equal(sentSignal.aborted,true);
assert.ok(timers.every(t=>t.canceled));
""")


def test_completed_read_removes_deadline_and_parent_abort_listener():
    _api("""
pendingBody=false;const parent=new AbortController();
const response=await apiFetch('/api/config',{signal:parent.signal});
assert.equal((await response.json()).success,true);
assert.ok(timers.every(t=>t.canceled));
parent.abort();assert.equal(sentSignal.aborted,false);
""")


def test_timed_out_settings_read_releases_inflight_state_and_can_retry():
    extra = r"""
const nodes=new Proxy({}, {get(target,key){return target[key]??=( {value:'',textContent:'',checked:false} )}});
const $=id=>nodes[id];
function setConfigFormReady(ready){nodes.ready=ready}
let configViewLoad=null;
""" + _source("async function loadConfigView(", "$('cfgReload')")
    _api("""
const first=loadConfigView();await new Promise(resolve=>setImmediate(resolve));
assert.equal(timers[0].canceled,false);timers[0].callback();await first;
assert.match(nodes.cfgStatus.textContent,/timed out/i);
assert.equal(configViewLoad,null);
pendingBody=false;await loadConfigView();
assert.equal(calls,2);assert.equal(nodes.ready,true);
assert.equal(nodes.cfgStatus.textContent,'');
""", extra)


def _coordination(scenario: str) -> None:
    setup = r"""
const nodes=new Proxy({}, {get(target,key){return target[key]??={value:'',textContent:'Loading…',innerHTML:'',style:{}}}});
const $=id=>nodes[id];
const esc=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
let responses={};
nodes.coordBoardRoot.value='C:/repo';
const requested=[];
async function fetchDashboardJson(path){requested.push(path);const name=path.split('/').pop(),value=responses[name];
  if(value instanceof Error)throw value;return await value}
const post=(path)=>fetchDashboardJson(path);
"""
    source = _source("let cachedBoardItems", "async function updateCardStatus(")
    _javascript(setup + source, scenario)


def test_coordination_rejected_reads_replace_loading_and_unknown_counts():
    _coordination("""
responses={plan_list:Error('hub paused: gaming mode active'),
  semaphore_status:Error('hub paused: gaming mode active')};
await loadCoordinationView();
assert.match(nodes.kanbanBoardContainer.innerHTML,/gaming mode active/);
assert.match(nodes.coordSemaphoresBody.innerHTML,/gaming mode active/);
assert.match(nodes.coordPlanProgressGrid.innerHTML,/gaming mode active/);
assert.doesNotMatch(nodes.coordBoardSummaryText.textContent,/Loading/);
assert.equal(nodes.overviewBoardCount.textContent,'—');
assert.equal(nodes.overviewSemCount.textContent,'—');
assert.doesNotMatch(nodes.overviewBoardSub.textContent,/healthy/);
renderKanbanBoard();renderSemaphoresTable();renderPlanProgressView();
assert.match(nodes.kanbanBoardContainer.innerHTML,/gaming mode active/);
""")


def test_coordination_business_rejections_are_not_empty_successful_views():
    _coordination("""
responses={plan_list:{success:false,error:'read denied <reason>'},
  semaphore_status:{success:false,error:'read denied'}};
await loadCoordinationView();
assert.match(nodes.kanbanBoardContainer.innerHTML,/read denied/);
assert.doesNotMatch(nodes.kanbanBoardContainer.innerHTML,/<reason>|No cards/);
assert.doesNotMatch(nodes.coordSemaphoresBody.innerHTML,/No semaphores/);
""")


def test_partial_coordination_failure_does_not_hide_loaded_board_or_survive_retry():
    _coordination("""
responses={plan_list:{success:true,plans:[{id:'release',title:'Release',lifecycle:'active',file_revision:'rev-1'}]},
  plan_board_view:{success:true,project_root:'C:/repo',columns:{planned:[{task_id:'one',plan_id:'release',plan_title:'Release',title:'Saved card',work_status:'planned',plan_file_revision:'rev-1'}],ready:[],in_progress:[],blocked:[],source_ready:[],done:[]}},
  semaphore_status:Error('semaphores unavailable')};
await loadCoordinationView();
assert.match(nodes.kanbanBoardContainer.innerHTML,/Saved card/);
assert.match(nodes.coordSemaphoresBody.innerHTML,/semaphores unavailable/);
assert.match(nodes.coordPlanProgressGrid.innerHTML,/Release/);
assert.match(nodes.coordPlanProgressGrid.innerHTML,/1 Planned/);
assert.equal(requested.some(path=>path.includes('milestone_')),false);
responses.semaphore_status={success:true,semaphores:{}};
await loadCoordinationView();
assert.doesNotMatch(nodes.coordSemaphoresBody.innerHTML,/unavailable/);
assert.equal(nodes.overviewSemCount.textContent,'0 / 0');
""")


def test_board_failure_does_not_claim_there_are_no_plan_tasks():
    _coordination("""
responses={plan_list:{success:true,plans:[]},plan_board_view:Error('board unavailable'),
  semaphore_status:{success:true,semaphores:{}}};
await loadCoordinationView();
assert.match(nodes.coordPlanProgressGrid.innerHTML,/board unavailable/);
assert.doesNotMatch(nodes.coordPlanProgressGrid.innerHTML,/No tasks/);
""")


def test_superseded_coordination_read_cannot_replace_newer_results():
    _coordination("""
let finishOld;
responses={plan_list:new Promise(resolve=>{finishOld=resolve}),
  semaphore_status:{success:true,semaphores:{}}};
const oldRead=loadCoordinationView();
responses.plan_list={success:true,plans:[]};
responses.plan_board_view={success:true,project_root:'C:/repo',columns:{planned:[{task_id:'new',plan_id:'p',plan_title:'P',title:'Current card',work_status:'planned',plan_file_revision:'rev-2'}],ready:[],in_progress:[],blocked:[],source_ready:[],done:[]}};
await loadCoordinationView();
finishOld({success:true,plans:[]});await oldRead;
assert.match(nodes.kanbanBoardContainer.innerHTML,/Current card/);
assert.doesNotMatch(nodes.kanbanBoardContainer.innerHTML,/old failure/);
""")


def test_workspace_read_failure_survives_filter_changes_and_retry_recovers():
    setup = r"""
const nodes=new Proxy({}, {get(target,key){return target[key]??={value:'',textContent:'',innerHTML:'',addEventListener(){}}}});
const $=id=>nodes[id];
const esc=value=>String(value).replaceAll('<','&lt;').replaceAll('>','&gt;');
let failed=true;
async function fetchDashboardJson(){if(failed)throw Error('workspace read unavailable');return {success:true,workspaces:[]}}
"""
    _javascript(setup + _source("let ragWorkspaces=", "async function loadActiveLeases("), """
await loadRagWorkspaces();
assert.match(nodes.ragWorkspacesList.innerHTML,/workspace read unavailable/);
renderRagWorkspaces();
assert.match(nodes.ragWorkspaceSummary.textContent,/unavailable/);
assert.doesNotMatch(nodes.ragWorkspacesList.innerHTML,/No RAG workspace/);
failed=false;await loadRagWorkspaces();
assert.match(nodes.ragWorkspaceSummary.textContent,/0 of 0/);
assert.doesNotMatch(nodes.ragWorkspacesList.innerHTML,/unavailable/);
""")
