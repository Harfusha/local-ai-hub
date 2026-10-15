from __future__ import annotations

import shutil
import subprocess
import re
import json
from html.parser import HTMLParser

from local_ai_hub.dashboard import DASHBOARD_HTML


def run_javascript(source: str, scenario: str) -> None:
    node = shutil.which("node")
    assert node, "Node.js required for dashboard behavior checks"
    script = "const assert=require('node:assert/strict');\n" + source + "\n" + scenario
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr or result.stdout


def extract(start: str, end: str) -> str:
    first = DASHBOARD_HTML.index(start)
    return DASHBOARD_HTML[first:DASHBOARD_HTML.index(end, first)]


def test_initial_form_fields_have_accessible_names():
    class Fields(HTMLParser):
        def __init__(self):
            super().__init__()
            self.label_depth = 0
            self.unnamed = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "label":
                self.label_depth += 1
            if tag in {"input", "select", "textarea"} and attrs.get("type") != "hidden":
                if not self.label_depth and not attrs.get("aria-label") and not attrs.get("aria-labelledby"):
                    self.unnamed.append(attrs.get("id", tag))

        def handle_endtag(self, tag):
            if tag == "label":
                self.label_depth -= 1

    fields = Fields()
    fields.feed(DASHBOARD_HTML.split("<script>", 1)[0])
    assert not fields.unnamed, fields.unnamed


def test_retired_dashboard_token_feature_is_absent():
    for retired in ("apiToken", "saveToken", "getSavedToken", "localAiHubToken", "X-LocalAI-Token", ".control-popover .token"):
        assert retired not in DASHBOARD_HTML, retired


def test_removed_pages_leave_no_orphan_control_handlers():
    for retired in ("archSvg", "archRefresh", "symbolGraphBtn", "modelPullName", "installedModelsList", "dbQueryInput", "sseStreamBadge", "sseReconnectBtn", "cmdClassify", "cmdGitDiffBtn", "intelRediscover"):
        assert retired not in DASHBOARD_HTML, retired


def test_literal_dom_references_have_a_rendered_target():
    identifiers = set(re.findall(r'\bid="([\w-]+)"', DASHBOARD_HTML))
    references = set(re.findall(r"\$\('([\w-]+)'\)", DASHBOARD_HTML))
    assert not references - identifiers, sorted(references - identifiers)


def test_complete_dashboard_script_parses_after_dead_code_removal():
    node = shutil.which("node")
    assert node
    source = DASHBOARD_HTML.split("<script>", 1)[1].rsplit("</script>", 1)[0]
    script = "new (require('node:vm').Script)(" + json.dumps(source) + ");"
    result = subprocess.run([node], input=script, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_retired_panels_do_not_keep_background_requests():
    for endpoint in ("/api/adoption", "/api/models/manage", "/api/db/query", "/api/agent-state/events/stream"):
        assert endpoint not in DASHBOARD_HTML


def test_incident_ui_uses_only_supported_read_and_record_actions():
    assert "action:'find',limit:100" in DASHBOARD_HTML
    for retired in ("resolveIncidentAction", "setIncidentIgnoredAction", "resolveFixInput", '<option value="ignored">Ignored</option>'):
        assert retired not in DASHBOARD_HTML


def test_project_text_input_layout_excludes_checkboxes():
    assert '.project-toolbar input{' not in DASHBOARD_HTML
    assert '.project-toolbar input:not([type=checkbox]):not([type=radio])' in DASHBOARD_HTML


def test_unauthorized_response_never_prompts_or_retries_for_a_token():
    source = extract("function scopeAgentOsRequest(", "function setFrontendVisionCaptureState(")
    run_javascript(source, """
let requests=0;
const nativeFetch=async(_path,options)=>{
  requests++;
  assert.equal(options.headers.get('X-LocalAI-Client'),'dashboard');
  assert.equal(options.headers.has('X-LocalAI-Token'),false);
  return {status:401};
};
(async()=>{
  assert.equal((await apiFetch('/private')).status,401);
  assert.equal(requests,1);
})();
""")


def test_agent_os_requests_require_explicit_repository_scope():
    source = extract("function scopeAgentOsRequest(", "async function apiFetch(")
    run_javascript(source, """
let root='';
const $=()=>({value:root});
assert.throws(()=>scopeAgentOsRequest('/api/agent-state/tasks'),/Choose a repository/);
root='C:/repo with spaces';
const get=scopeAgentOsRequest('/api/agent-state/tasks?limit=100');
assert.equal(new URL(get.path,'http://localhost').searchParams.get('root'),root);
const post=scopeAgentOsRequest('/api/agent-state/tasks',{method:'POST',body:JSON.stringify({action:'create',contract:{goal:'A task'}})});
assert.equal(JSON.parse(post.options.body).root,root);
assert.equal(JSON.parse(post.options.body).contract.goal,'A task');
assert.equal(scopeAgentOsRequest('/api/live?after=0').path,'/api/live?after=0');
""")


def test_task_memory_requires_task_identity_before_submission():
    source = extract("async function submitRecordMemory(", "function renderIncidentModal(")
    run_javascript(source, """
const nodes={newMemKey:{value:'fact'},newMemVal:{value:'value'},newMemScope:{value:'task'},newMemKind:{value:'fact'},newMemTaskId:{value:''},recordMemStatus:{textContent:''}};
const $=id=>nodes[id];let calls=0;
const esc=String;
const post=async(_path,payload)=>{calls++;assert.equal(payload.task_id,'task_123');return {success:false,error:'fixture refusal'}};
(async()=>{
  await submitRecordMemory({preventDefault(){}});
  assert.equal(calls,0);
  assert.match(nodes.recordMemStatus.textContent,/Task ID/);
  nodes.newMemTaskId.value='task_123';
  await submitRecordMemory({preventDefault(){}});
  assert.equal(calls,1);
})();
""")


def test_trace_metadata_placeholder_is_not_presented_as_captured_input():
    source = extract("function tracePrimaryInput(", "function traceMainContent(")
    run_javascript(source, """
assert.equal(tracePrimaryInput({capture_status:'metadata_only',field_count:4}),undefined);
assert.deepEqual(tracePrimaryInput({prompt:'User task',model:'selected model'}),{prompt:'User task'});
assert.deepEqual(tracePrimaryInput({capture_status:'metadata_only',prompt:'real user data'}),{capture_status:'metadata_only',prompt:'real user data'});
""")


def test_dashboard_json_rejects_http_and_business_failures():
    source = extract("async function fetchDashboardJson(", "const ACTIVITY_MODES=")
    run_javascript(source, """
let response={ok:true,status:200,json:async()=>({success:true,items:[]})};
const apiFetch=async()=>response;
(async()=>{
  assert.deepEqual(await fetchDashboardJson('/test'),{success:true,items:[]});
  response={ok:true,status:200,json:async()=>({success:false,error:'operation refused'})};
  await assert.rejects(fetchDashboardJson('/test'),/operation refused/);
  response={ok:false,status:503,json:async()=>({error:'service unavailable'})};
  await assert.rejects(fetchDashboardJson('/test'),/service unavailable/);
  response={ok:false,status:502,json:async()=>{throw Error('invalid JSON')}};
  await assert.rejects(fetchDashboardJson('/test'),/502/);
})();
""")


def test_agent_os_partial_failure_remains_visible_after_filtering():
    source = extract("async function loadAgentOsView()", "function switchAgentOsSubtab(")
    run_javascript(source, """
let agentOsTasks=[],agentOsMemories=[],agentOsIncidents=[],agentOsLoadErrors={};
let renders=0;
const $=()=>({value:"C:/repo"});
const setAgentOsScopeReady=()=>{};
const renderAgentOsView=()=>renders++;
const fetchDashboardJson=async path=>{
  if(path.endsWith('/tasks'))throw Error('tasks unavailable');
  return path.endsWith('/memory')?{records:[{key:'fact'}]}:{incidents:[]};
};
const post=async()=>({incidents:[]});
(async()=>{
  await loadAgentOsView();
  assert.equal(renders,1);
  assert.match(agentOsLoadErrors.tasks,/tasks unavailable/);
  assert.equal(agentOsMemories.length,1);
  assert.equal(agentOsLoadErrors.memory,undefined);
})();
""")


def test_worktree_and_arena_failures_do_not_look_successful():
    source = extract("async function loadWorktrees()", "let cachedTrajTasks=")
    setup = """
const nodes={},handlers={},alerts=[];
const $=id=>nodes[id]??=( {value:'C:/missing',textContent:'',innerHTML:'',disabled:false,addEventListener:(_,fn)=>handlers[id]=fn} );
const document={addEventListener:()=>{}};
"""
    run_javascript(setup + source, """
const esc=s=>String(s).replaceAll('<','&lt;');
const rows=()=>{};
const apiFetch=async()=>{throw Error('use checked JSON loader')};
const fetchDashboardJson=async()=>{throw Error('not a repository')};
const post=async()=>({success:false,error:'model unavailable'});
const alert=s=>alerts.push(s);
(async()=>{
  await loadWorktrees();
  assert.equal($('worktreeSummary').textContent,'Worktrees unavailable');
  assert.match($('worktreesTable').innerHTML,/not a repository/);
  await handlers.arenaRunBtn();
  assert.match($('arenaFastStats').innerHTML,/Error/);
  assert.match($('arenaSmartOutput').textContent,/model unavailable/);
  assert.equal($('arenaRunBtn').disabled,false);
})();
""")


def test_worktree_empty_root_does_not_query_implicit_repository():
    source = extract("async function loadWorktrees()", "$('refreshWorktreesBtn')")
    run_javascript(source, """
const nodes={};
const $=id=>nodes[id]??={value:'',textContent:'',innerHTML:'',disabled:false};
const fetchDashboardJson=async()=>{throw Error('must not query implicit root')};
(async()=>{
  await loadWorktrees();
  assert.match($('worktreeSummary').textContent,/Choose a repository/);
  assert.equal($('pruneWorktreesBtn').disabled,true);
})();
""")


def test_telemetry_availability_distinguishes_zero_missing_and_dropped_data():
    assert "function dashboardTelemetryState" in DASHBOARD_HTML
    source = extract("function dashboardTelemetryState", "function dashboardHealth(")
    run_javascript(source, """
const empty=dashboardTelemetryState({});
assert.equal(empty.available,false);
assert.equal(dashboardTelemetryState({enabled:false}).available,false);
assert.equal(dashboardTelemetryState({data_available:false,net_cloud_token_delta_est:0}).available,false);
const zero=dashboardTelemetryState({data_available:true,net_cloud_token_delta_est:0,writer:{}});
assert.equal(zero.available,true);
assert.equal(zero.complete,true);
assert.equal(dashboardTelemetryState({data_available:true,writer:{dropped:4}}).complete,false);
assert.equal(dashboardTelemetryState({data_available:true,writer:{writer_errors:2}}).complete,false);
assert.equal(dashboardTelemetryState({data_available:true,accounting_boundary_incomplete:true}).complete,false);
assert.equal(dashboardTelemetryState({data_available:true,stale:true}).available,false);
assert.equal(formatEstimatedUsd(0.0008),'≈ $0.0008');
assert.equal(formatEstimatedUsd(0),'≈ $0.00');
assert.equal(formatEstimatedUsd(-0.0008),'≈ −$0.0008');
assert.equal(formatEstimatedUsd(1.234),'≈ $1.23');
""")


def test_overview_health_reports_failed_telemetry_instead_of_healthy():
    source = extract("function dashboardHealth(", "function dashboardFreshness(")
    run_javascript(source, """
const base={hub_online:true,ollama_online:true,headless:{state:'running'}};
assert.equal(dashboardHealth({...base,observability:{writer:{dropped:12}}}).level,'attention');
assert.match(dashboardHealth({...base,observability:{writer:{dropped:12}}}).reason,/telemetry/i);
assert.equal(dashboardHealth({...base,observability:{data_available:false}}).level,'attention');
assert.equal(dashboardHealth({...base,observability:{data_available:true,writer:{dropped:0,writer_errors:0}}}).level,'healthy');
assert.equal(dashboardHealth({...base,degraded:true,dependency_status:{'preprocessing.status':{degraded:true}}}).level,'degraded');
""")


def test_failed_project_action_is_visible_and_does_not_refresh_as_success():
    source = extract("async function projectAction(root, action)", "$('regProjectBtn').onclick")
    run_javascript(source, """
let messages=[],polls=0;
const alert=message=>messages.push(message);
const pollStatus=async()=>{polls++};
let post=async()=>({success:false,error:'project unavailable'});
(async()=>{
  await projectAction('C:/repo','refresh');
  assert.equal(polls,0);
  assert.match(messages[0],/project unavailable/);
  post=async()=>({success:true});
  await projectAction('C:/repo','pause');
  assert.equal(polls,1);
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_preprocessing_summary_separates_project_count_from_capacity():
    assert "function preprocessingSummary" in DASHBOARD_HTML
    source = extract("function preprocessingSummary", "function dashboardHealth(")
    run_javascript(source, """
const running=preprocessingSummary({active_projects:58,processing_projects:4,max_preprocessing_projects:3});
assert.equal(running.available,true);
assert.match(running.text,/4 processing projects/);
assert.match(running.text,/3 concurrent slots/);
assert(!running.text.includes('4/3'));
assert.equal(preprocessingSummary({success:false}).available,false);
assert.equal(preprocessingSummary({}, {'preprocessing.status':{degraded:true}}).available,false);
""")


def test_metric_cards_hide_false_zero_and_explain_partial_estimates():
    assert "function renderTelemetryMetrics" in DASHBOARD_HTML
    source = extract("function dashboardTelemetryState", "function dashboardHealth(")
    run_javascript(source, """
const nodes={};
const $=id=>nodes[id]||(nodes[id]={textContent:'0',classList:{toggle(){}}});
const n=value=>String(Number(value)||0);
let sloScope='process';
renderTelemetryMetrics({data_available:false});
assert.equal(nodes.tokensSaved.textContent,'Unavailable');
assert.equal(nodes.dollarsSaved.textContent,'Unavailable');
assert.match(nodes.efficiencyStatus.textContent,/unavailable/i);
renderTelemetryMetrics({data_available:true,net_cloud_token_delta_est:0,tool_accounting_events:0});
assert.equal(nodes.tokensSaved.textContent,'0');
assert.match(nodes.tokensSavedSub.textContent,/No accounted calls/);
renderTelemetryMetrics({data_available:true,net_cloud_token_delta_est:-42,estimated_savings_usd:-0.0008,tool_accounting_events:2,writer:{dropped:4}});
assert.equal(nodes.dollarsSaved.textContent,'≈ −$0.0008');
assert.match(nodes.efficiencyStatus.textContent,/Incomplete/);
assert.match(nodes.tokensSavedSub.textContent,/Since restart/);
assert.match(nodes.efficiencyBreakdown.textContent,/4 records dropped/);
""")


def test_configuration_controls_stay_disabled_until_loaded_and_after_error():
    assert "function setConfigFormReady" in DASHBOARD_HTML
    source = extract("function setConfigFormReady", "$('cfgReload').onclick=loadConfigView;")
    run_javascript(source, """
const nodes={};
const $=id=>nodes[id]||(nodes[id]={disabled:false,textContent:'',checked:false});
const controls=[{disabled:false},{disabled:false}];
const document={querySelectorAll:()=>controls};
let finish;
let apiFetch=()=>new Promise(resolve=>{finish=resolve});
(async()=>{
  const pending=loadConfigView();
  assert(controls.every(c=>c.disabled));
  assert.equal(nodes.cfgSave.disabled,true);
  finish({ok:true,json:async()=>({success:true,config:{features:{repo:true}}})});
  await pending;
  assert(controls.every(c=>!c.disabled));
  assert.equal(nodes.cfgSave.disabled,false);
  apiFetch=async()=>{throw Error('offline')};
  await loadConfigView();
  assert.equal(nodes.cfgSave.disabled,true);
  assert.equal(nodes.cfgReset.disabled,true);
  assert.match(nodes.cfgStatus.textContent,/offline/);
})().catch(error=>{console.error(error);process.exitCode=1});
""")
