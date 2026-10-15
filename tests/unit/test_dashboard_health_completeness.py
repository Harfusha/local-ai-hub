from __future__ import annotations

import shutil
import subprocess

from local_ai_hub.dashboard import DASHBOARD_HTML


def _extract(start: str, end: str) -> str:
    first = DASHBOARD_HTML.index(start)
    return DASHBOARD_HTML[first : DASHBOARD_HTML.index(end, first)]


def _deferred_javascript_check(source: str, scenario: str) -> None:
    node = shutil.which("node")
    assert node, "Node.js required for dashboard behavior checks"
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
    source += _extract("function dashboardHealth(", "function dashboardFreshness(")
    source += _extract("function preprocessingSummary(", "function telemetryPeriod(")
    _deferred_javascript_check(
        "const n=v=>String(v??0);\n" + source,
        """
const healthy={hub_online:true,ollama_online:true,headless:{state:'running'},
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
const missingStats=preprocessingSummary({success:true,max_preprocessing_projects:3,projects:[]},
  {'preprocessing.stats':{degraded:true}});
assert.equal(missingStats.available,true);
assert.equal(missingStats.statsAvailable,false);
assert.match(missingStats.text,/unknown concurrent slots/);
""",
    )
