from __future__ import annotations

import shutil
import subprocess

import pytest

from local_ai_hub.dashboard import DASHBOARD_HTML


def _extract(start: str, end: str) -> str:
    first = DASHBOARD_HTML.index(start)
    return DASHBOARD_HTML[first : DASHBOARD_HTML.index(end, first)]


def _deferred_javascript_check(source: str, scenario: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js unavailable; dashboard UI gate NOT VERIFIED")
    script = "const assert=require('node:assert/strict');\n" + source + "\n" + scenario
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr or result.stdout


def test_telemetry_render_warns_on_unknown_or_incomplete_writer_coverage() -> None:
    source = _extract("function dashboardTelemetryState(", "function preprocessingSummary(")
    _deferred_javascript_check(
        "const els={};const $=id=>els[id]||(els[id]={textContent:'',classList:{toggle:(k,v)=>{els[id][k]=v}}});"
        "const n=v=>String(v??0);const sloScope='process';\n" + source,
        """
const base={enabled:true,data_available:true,scope:'process',tool_accounting_events:0,
  net_cloud_token_delta_est:0,cohorts:{agent_http:{events:0,failures:0},policy_rejection:{events:0}},
  writer:{dropped:0,writer_errors:0,pending:0,activity_observed:true,accounting_balanced:true},
  detail:{incomplete:false},summary_cache_stale:false};
renderTelemetryMetrics(base);
assert.match(els.efficiencyStatus.textContent,/No accounted tool calls yet/);
assert.equal(els.efficiencyStatus['warn-t'],false);
renderTelemetryMetrics({...base,summary_cache_stale:true});
assert.match(els.efficiencyStatus.textContent,/Cached telemetry summary is stale/);
assert.equal(els.efficiencyStatus['warn-t'],true);
renderTelemetryMetrics({...base,writer:{...base.writer,pending:2}});
assert.match(els.efficiencyStatus.textContent,/2 pending records/);
renderTelemetryMetrics({...base,writer:{...base.writer,accounting_balanced:false}});
assert.match(els.efficiencyStatus.textContent,/unavailable or unbalanced/);
renderTelemetryMetrics({...base,writer:{...base.writer,activity_observed:false}});
assert.match(els.efficiencyStatus.textContent,/activity was not observed/);
""",
    )


def test_project_errors_and_unknown_inventory_are_functional_health_warnings() -> None:
    source = _extract("function dashboardPreprocessingHealth(", "function dashboardTelemetryState(")
    source += _extract("function dashboardTelemetryState(", "function formatEstimatedUsd(")
    source += _extract("function dashboardHealth(", "function dashboardFreshness(")
    source += _extract("function preprocessingSummary(", "function telemetryPeriod(")
    _deferred_javascript_check(
        "const n=v=>String(v??0);\n" + source,
        """
const healthy={hub_online:true,ollama_online:true,headless:{state:'running'},
  observability:{enabled:true,data_available:true,net_cloud_token_delta_est:0,
    cohorts:{agent_http:{events:0,failures:0},policy_rejection:{events:0}},
    writer:{dropped:0,writer_errors:0,pending:0,activity_observed:true,accounting_balanced:true},
    detail:{incomplete:false},summary_cache_stale:false},
  preprocessing:{success:true,projects:[{status:'complete',last_error:'historical text'}]}};
assert.equal(dashboardHealth(healthy).level,'healthy');
const failed={...healthy,preprocessing:{success:true,projects:[{status:'error',last_error:'current failure'}]}};
assert.equal(dashboardHealth(failed).level,'attention');
assert.match(dashboardHealth(failed).reason,/1 current preprocessing project report error/);
const errorBadge=dashboardHealthBadge(failed);
assert.equal(errorBadge.className,'warn-t');
assert.match(errorBadge.degradedLabel,/1 preprocessing project error/);
const unknown={...healthy,preprocessing:{success:true}};
assert.equal(dashboardHealth(unknown).level,'attention');
assert.match(dashboardHealth(unknown).reason,/project status is unknown/);
const unknownBadge=dashboardHealthBadge(unknown);
assert.equal(unknownBadge.className,'warn-t');
assert.match(unknownBadge.degradedLabel,/preprocessing status unknown/);
const partial={...healthy,dependency_status:{'preprocessing.stats':{degraded:true}}};
assert.equal(dashboardHealth(partial).level,'attention');
assert.match(dashboardHealth(partial).reason,/statistics are unavailable/);
assert.equal(dashboardHealthBadge({...failed,hub_online:false}).className,'bad-t');
const rows=preprocessingSummary({success:true,max_preprocessing_projects:3,projects:[
  {status:'running'},{status:'complete',last_error:'old error'}]},{});
assert.equal(rows.available,true);
assert.match(rows.text,/2 registered · 1 currently running · 3 concurrent slots/);
const noRows=preprocessingSummary({success:true},{});
assert.equal(noRows.available,false);
assert.match(noRows.text,/status unknown/);
const disabledByProject={...healthy,preprocessing:{enabled:false}};
assert.equal(dashboardHealth(disabledByProject).level,'healthy');
assert.equal(dashboardHealthBadge(disabledByProject).className,'ok');
assert.match(dashboardHealthBadge(disabledByProject).degradedLabel,/preprocessing disabled/);
assert.equal(preprocessingSummary({enabled:false},{}).available,true);
const disabledByFeature={...disabledByProject,preprocessing:{success:true},features:{preprocessing:false}};
assert.equal(dashboardHealth(disabledByFeature).level,'healthy');
assert.equal(dashboardHealthBadge(disabledByFeature).className,'ok');
const missingStats=preprocessingSummary({success:true,max_preprocessing_projects:3,projects:[]},
  {'preprocessing.stats':{degraded:true}});
assert.equal(missingStats.available,true);
assert.equal(missingStats.statsAvailable,false);
assert.match(missingStats.text,/unknown concurrent slots/);
""",
    )


def test_overall_health_requires_complete_advertised_telemetry_coverage() -> None:
    source = _extract("function dashboardTelemetryState(", "function formatEstimatedUsd(")
    source += _extract("function dashboardHealth(", "function dashboardFreshness(")
    _deferred_javascript_check(
        "const n=v=>String(v??0);\n" + source,
        """
const base={hub_online:true,ollama_online:true,headless:{state:'running'},observability:{
  enabled:true,data_available:true,activity_observed:true,accounting_balanced:true,
  net_cloud_token_delta_est:0,cohorts:{agent_http:{events:0,failures:0},policy_rejection:{events:0}},
  writer:{dropped:0,writer_errors:0,pending:0,activity_observed:true,accounting_balanced:true},
  detail:{incomplete:false},summary_cache_stale:false}};
assert.equal(dashboardHealth(base).level,'healthy');
assert.equal(dashboardHealth({...base,observability:{...base.observability,writer:{...base.observability.writer,pending:5}}}).level,'healthy');
for(const observability of [
  {...base.observability,data_available:false},
  {...base.observability,writer:{...base.observability.writer,activity_observed:false}},
  {...base.observability,writer:{...base.observability.writer,accounting_balanced:false}},
  {...base.observability,writer:{...base.observability.writer,pending:25}},
  {...base.observability,summary_cache_stale:true},
  {...base.observability,detail:{incomplete:true}},
]){
  const result=dashboardHealth({...base,observability});
  assert.equal(result.level,'attention');
  assert.match(result.reason,/telemetry/);
}
const offline=dashboardHealth({...base,hub_online:false,observability:{...base.observability,data_available:false}});
assert.equal(offline.level,'degraded');
""",
    )
