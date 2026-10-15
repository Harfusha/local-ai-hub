from __future__ import annotations

import shutil
import subprocess

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
