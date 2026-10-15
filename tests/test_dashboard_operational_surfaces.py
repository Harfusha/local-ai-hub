from local_ai_hub import http_server
from local_ai_hub.dashboard import DASHBOARD_HTML


def test_dashboard_template_keeps_primary_content_and_faithful_raw_payload():
    assert DASHBOARD_HTML.startswith("<!doctype html>")
    assert "Input" in DASHBOARD_HTML
    assert "Output" in DASHBOARD_HTML
    assert "Complete endpoint input" not in DASHBOARD_HTML
    assert "Complete endpoint output" not in DASHBOARD_HTML
    assert "Complete JSON payload" in DASHBOARD_HTML
    assert "tracePanel('raw','Raw',()=>traceRaw(detail),true)" in DASHBOARD_HTML
    assert "JSON.stringify(payload,null,2)" in DASHBOARD_HTML
    assert "JSON.stringify(traceSanitizeValue(payload)" not in DASHBOARD_HTML


def test_served_dashboard_discloses_trace_access_and_retention_policy():
    html = http_server._dashboard_html_with_trace_notice()
    assert "full input/output only when enabled" in html
    assert "complete stored details shown as recorded" in html
    assert "local access only" in html
    assert "separate local retention policy" in html


def test_dashboard_has_live_detailed_telemetry_toggle():
    assert 'id="detailedTelemetryToggle"' in DASHBOARD_HTML
    assert "debug_traces.enabled" in DASHBOARD_HTML
    assert "Detailed telemetry:" in DASHBOARD_HTML
    assert "traceRevealRedactedDetails" not in DASHBOARD_HTML
    assert "Complete endpoint input" not in DASHBOARD_HTML
    assert "Complete endpoint output" not in DASHBOARD_HTML
    assert "Complete JSON payload" in DASHBOARD_HTML
    assert "JSON.stringify(payload,null,2)" in DASHBOARD_HTML
    assert "tracePanel('raw','Raw',()=>traceRaw(detail),true)" in DASHBOARD_HTML


def test_operations_views_name_distinct_records_and_trace_availability() -> None:
    assert "Live scheduler work" in DASHBOARD_HTML
    assert "Request history" in DASHBOARD_HTML
    assert "Trace availability" in DASHBOARD_HTML
    assert "Agent task runs" in DASHBOARD_HTML
    assert "function requestTraceAvailability(request)" in DASHBOARD_HTML


def test_dashboard_distinguishes_unknown_ollama_probe_from_offline() -> None:
    start = DASHBOARD_HTML.index("function dashboardHealth(")
    end = DASHBOARD_HTML.index("function dashboardFreshness(", start)
    health_source = DASHBOARD_HTML[start:end]

    assert "ollama_status" in health_source
    assert "Ollama status is unknown" in health_source
    assert "Ollama is offline" in health_source


def test_dashboard_marks_degraded_live_status_and_retries_with_backoff() -> None:
    start = DASHBOARD_HTML.index("async function pollStatus(")
    end = DASHBOARD_HTML.index("const statusPoller=createDashboardStatusPoller", start)
    poll_source = DASHBOARD_HTML[start:end]

    assert "if(!r.ok)throw new Error(`status request failed (HTTP ${r.status})`)" in poll_source
    assert "if(s.success===false){$('conn').textContent=s.snapshot_stale===true?'stale':'degraded';$('conn').className='pill warn-t'" in poll_source
    assert "return false;" in poll_source


def test_dashboard_exposes_activity_mode_and_reports_http_failures() -> None:
    assert 'id="activityModeBadge"' in DASHBOARD_HTML
    assert 'id="activityModeActive"' in DASHBOARD_HTML
    assert 'id="activityModeGaming"' in DASHBOARD_HTML
    assert 'id="activityModeMaintenance"' in DASHBOARD_HTML
    start = DASHBOARD_HTML.index("function activityModeFailure")
    end = DASHBOARD_HTML.index("async function loadConfigView", start)
    mode_source = DASHBOARD_HTML[start:end]
    assert "'/api/mode'" in mode_source
    assert "'/api/admin/mode'" in mode_source
    assert "401" in mode_source
    assert "invalid mode" in mode_source.lower()
    fetch_start = DASHBOARD_HTML.index("async function apiFetch")
    fetch_end = DASHBOARD_HTML.index("function setFrontendVisionCaptureState", fetch_start)
    assert "X-LocalAI-Token" not in DASHBOARD_HTML[fetch_start:fetch_end]
    assert "X-LocalAI-Client" in DASHBOARD_HTML[fetch_start:fetch_end]
    assert "Active" in DASHBOARD_HTML
    assert "Gaming" in DASHBOARD_HTML
    assert "Maintenance" in DASHBOARD_HTML
    assert 'id="activityModeSelect"' not in DASHBOARD_HTML
    assert 'id="activityModeApply"' not in DASHBOARD_HTML
    assert "button.onclick=()=>applyActivityMode(button.dataset.activityMode)" in DASHBOARD_HTML
    assert "buttons.forEach(button=>button.disabled=true)" in mode_source
    assert "Updating mode…" in mode_source
    assert "Checking mode…" in DASHBOARD_HTML
    assert "gaming:'GAMING / PAUSED'" in DASHBOARD_HTML


def test_dashboard_requires_server_confirmation_before_reporting_mode_update() -> None:
    start = DASHBOARD_HTML.index("async function applyActivityMode(mode)")
    end = DASHBOARD_HTML.index("async function loadConfigView", start)
    mode_source = DASHBOARD_HTML[start:end]

    assert "data.mode||mode" not in mode_source
    assert "const confirmed=data.mode;" in mode_source
    assert "!ACTIVITY_MODES.includes(confirmed)||confirmed!==mode" in mode_source
    projection_start = DASHBOARD_HTML.index("function projectActivityModeTransition(confirmed,data){")
    projection_end = DASHBOARD_HTML.index("\nasync function refreshActivityMode", projection_start)
    projection_source = DASHBOARD_HTML[projection_start:projection_end]
    assert "failures.push('VRAM unload incomplete')" in projection_source


def _run_dashboard_apply_cases(cases):
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    assert node is not None, "Node.js is required for the bounded dashboard behavior test"

    def extract(start_marker, end_marker):
        start = DASHBOARD_HTML.index(start_marker)
        end = DASHBOARD_HTML.index(end_marker, start)
        return DASHBOARD_HTML[start:end].strip()

    has_projection = "function projectActivityModeTransition(confirmed,data){" in DASHBOARD_HTML
    render_js = extract("function renderActivityMode(mode){", "\nfunction activityModeFailure")
    failure_end = "\nfunction projectActivityModeTransition" if has_projection else "\nasync function refreshActivityMode"
    failure_js = extract("function activityModeFailure(response,data){", failure_end)
    projection_js = extract("function projectActivityModeTransition(confirmed,data){", "\nasync function refreshActivityMode") if has_projection else ""
    apply_js = extract("async function applyActivityMode(mode){", "\nasync function loadConfigView")
    script = f"""
const vm=require('node:vm');
const activityModeLabels={{active:'Active',gaming:'GAMING / PAUSED',maintenance:'Maintenance'}};
const sources={json.dumps([render_js, failure_js, projection_js, apply_js])};
const cases={json.dumps(cases)};
async function runCase(item){{
  const badge={{dataset:{{mode:'active'}},className:'pill ok',textContent:'Mode: Active'}};
  const status={{textContent:''}};
  const buttons=['active','gaming','maintenance'].map(mode=>({{dataset:{{activityMode:mode}},disabled:false,setAttribute(name,value){{this[name]=value;}}}}));
  const sandbox=vm.createContext({{
    ACTIVITY_MODES:['active','gaming','maintenance'],
    activityModeLabels,
    activityModeStatusPolls:0,
    activityModeTransitionNotice:null,
    document:{{querySelectorAll:()=>buttons}},
    $:(id)=>({{activityModeBadge:badge,activityModeStatus:status}}[id]||null),
    apiFetch:async()=>({{ok:item.ok,status:item.status,json:async()=>item.data}}),
    setTimeout:()=>0,
  }});
  vm.runInContext(sources.join('\\n'),sandbox,{{timeout:1500}});
  const returned=await vm.runInContext(`applyActivityMode(${{JSON.stringify(item.mode)}})`,sandbox);
  return {{name:item.name,returned,badgeMode:badge.dataset.mode,badgeText:badge.textContent,status:status.textContent,buttonsEnabled:buttons.every(button=>!button.disabled)}};
}}
Promise.all(cases.map(runCase)).then(results=>console.log(JSON.stringify(results))).catch(error=>{{console.error(error);process.exitCode=1;}});
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True, timeout=5)
    return json.loads(result.stdout)


def test_dashboard_reports_incomplete_vram_unload_after_gaming_pause() -> None:
    result = _run_dashboard_apply_cases([{
        "name": "runtime_unload",
        "mode": "gaming",
        "ok": True,
        "status": 200,
        "data": {
            "success": True,
            "mode": "gaming",
            "runtime_unload": {"success": False},
            "accelerator_release": {"success": True},
        },
    }])[0]

    assert result["returned"] is True
    assert result["badgeMode"] == "gaming"
    assert result["badgeText"] == "Mode: GAMING / PAUSED"
    assert result["status"] == (
        "Mode persisted as GAMING / PAUSED. Mode transition incomplete: "
        "VRAM unload incomplete."
    )
    assert result["buttonsEnabled"] is True


def test_operator_surfaces_report_all_transition_failures() -> None:
    results = _run_dashboard_apply_cases([
        {
            "name": "accelerator_release",
            "mode": "gaming",
            "ok": True,
            "status": 200,
            "data": {
                "success": True,
                "mode": "gaming",
                "runtime_unload": {"success": True},
                "accelerator_release": {"success": False},
            },
        },
        {
            "name": "job_cancellation",
            "mode": "maintenance",
            "ok": True,
            "status": 200,
            "data": {
                "success": True,
                "mode": "maintenance",
                "job_cancellation": {"success": False},
            },
        },
        {
            "name": "complete",
            "mode": "gaming",
            "ok": True,
            "status": 200,
            "data": {
                "success": True,
                "mode": "gaming",
                "runtime_unload": {"success": True},
                "accelerator_release": {"success": True},
            },
        },
        {
            "name": "unauthorized",
            "mode": "gaming",
            "ok": False,
            "status": 401,
            "data": {"success": False, "error": "unauthorized"},
        },
    ])
    accelerator, cancellation, complete, unauthorized = results

    assert accelerator["returned"] is True
    assert accelerator["badgeMode"] == "gaming"
    assert accelerator["badgeText"] == "Mode: GAMING / PAUSED"
    assert accelerator["status"] == (
        "Mode persisted as GAMING / PAUSED. Mode transition incomplete: "
        "accelerator release incomplete."
    )
    assert "Mode set to " not in accelerator["status"]
    assert accelerator["buttonsEnabled"] is True

    assert cancellation["returned"] is True
    assert cancellation["badgeMode"] == "maintenance"
    assert cancellation["badgeText"] == "Mode: Maintenance"
    assert cancellation["status"] == (
        "Mode persisted as Maintenance. Mode transition incomplete: "
        "job cancellation incomplete."
    )
    assert cancellation["buttonsEnabled"] is True

    assert complete["returned"] is True
    assert complete["badgeMode"] == "gaming"
    assert complete["status"] == "Mode set to GAMING / PAUSED."
    assert "incomplete" not in complete["status"]
    assert complete["buttonsEnabled"] is True

    assert unauthorized["returned"] is False
    assert unauthorized["badgeMode"] == "active"
    assert unauthorized["status"] == "Unauthorized (HTTP 401); check the API token."
    assert unauthorized["buttonsEnabled"] is True


def test_dashboard_route_serves_live_http_document(monkeypatch) -> None:
    import threading
    import urllib.request
    from types import SimpleNamespace

    from local_ai_hub import http_server

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={
        "monitoring": {"dashboard_enabled": True},
        "features": {"dashboard": True},
    }))
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/dashboard", timeout=3) as response:
            body = response.read().decode("utf-8")
            assert response.status == 200
            assert response.headers.get_content_type() == "text/html"
        assert 'id="activityModeBadge"' in body
        assert "Ollama is offline" in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_recent_request_table_reserves_trace_and_duration_columns() -> None:
    assert ".work-panel-3 th:nth-child(8){width:12%}" in DASHBOARD_HTML
    assert ".work-panel-3 th:nth-child(9){width:7%}" in DASHBOARD_HTML
    assert ".work-panel-3 td:nth-child(8),.work-panel-3 td:nth-child(9){white-space:nowrap" in DASHBOARD_HTML


def test_projects_and_bundles_expose_canonical_identity_and_readiness() -> None:
    assert "Repository identity" in DASHBOARD_HTML
    assert "Group worktrees" in DASHBOARD_HTML
    assert "function projectIdentity(project)" in DASHBOARD_HTML
    assert "Bundle readiness" in DASHBOARD_HTML
    assert "Index contents" in DASHBOARD_HTML


def test_rag_reliability_and_events_have_operational_filters() -> None:
    assert "Search RAG workspaces" in DASHBOARD_HTML
    assert "Workspace identity" in DASHBOARD_HTML
    assert "Runtime health &amp; recorded history" in DASHBOARD_HTML
    assert "Historical failures and unclean exits" in DASHBOARD_HTML
    assert "Event severity" in DASHBOARD_HTML
    assert "Event source" in DASHBOARD_HTML


def test_live_events_with_trace_id_link_to_trace_inspector() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function renderEvents(events=liveEvents)") : DASHBOARD_HTML.index(
            "async function pollEvents(isCurrent="
        )
    ]
    assert "traceId=e.trace_id" in source
    assert "traceAttr=traceId?" in source
    assert "data-trace-id" in source
    assert "data-detail=\"${id}\"" in source


def test_live_pollers_skip_overlapping_requests() -> None:
    pollers_start = DASHBOARD_HTML.index("let liveEvents=[]")
    pollers_end = DASHBOARD_HTML.index("function renderBundles(s)", pollers_start)
    pollers = DASHBOARD_HTML[pollers_start:pollers_end]
    assert "statusPoller.start();" in DASHBOARD_HTML[:pollers_start]
    assert "pollStatus()" not in pollers
    trace_poller = DASHBOARD_HTML[DASHBOARD_HTML.index("async function pollTraces(isCurrent=") : DASHBOARD_HTML.index("$('traceRefresh')")]
    assert "let liveEvents=[],eventsPollInFlight=false,tracesPollInFlight=false" in pollers
    assert "if(!isCurrent()||tracesPollInFlight)return false" in trace_poller
    assert "if(!isCurrent()||eventsPollInFlight)return false" in pollers
    assert "finally{tracesPollInFlight=false;" in trace_poller
    assert "finally{eventsPollInFlight=false;" in pollers


def test_trace_inspector_consumes_pages_with_hard_response_budget() -> None:
    start = DASHBOARD_HTML.index("async function openTrace(id)")
    end = DASHBOARD_HTML.index("function openModal", start)
    source = DASHBOARD_HTML[start:end]

    assert "limit=100&max_bytes=8388608" in source
    assert "max_bytes=134217728" not in source
    assert "if(d.cursor_reset){traceSeq=0;traceEvents=[];traceEventTotal=0;}" in source
    assert "if(d.terminal&&!d.has_more" in source


def test_status_poller_respects_visibility_unchanged_state_and_jitter() -> None:
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        import pytest

        pytest.skip("Node.js is required for dashboard poller behavior test")
    poller_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function createDashboardStatusPoller") : DASHBOARD_HTML.index(
            "async function apiFetch"
        )
    ]
    harness = r"""
const assert = require('node:assert/strict');
let visible = true;
let pollCount = 0;
const outcomes = [false, false, true];
const timers = [];
const poller = createDashboardStatusPoller(async () => {
  pollCount += 1;
  return outcomes.shift();
}, {
  baseDelay: 1000,
  maxDelay: 8000,
  isVisible: () => visible,
  setTimer: (callback, delay) => { const timer = {callback, delay, canceled: false}; timers.push(timer); return timer; },
  clearTimer: timer => { timer.canceled = true; },
  random: () => 0.25
});
const activeTimer = () => [...timers].reverse().find(timer => !timer.canceled);
const settle = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  assert.equal(shouldRefreshDashboardStatus({online: true}), true);
  assert.equal(shouldRefreshDashboardStatus({online: true}), false);
  assert.equal(shouldRefreshDashboardStatus({online: false}), true);
  poller.start();
  assert.equal(activeTimer().delay, 0);
  activeTimer().callback(); await settle();
  assert.equal(activeTimer().delay, 900);
  activeTimer().callback(); await settle();
  assert.equal(activeTimer().delay, 1800);
  const hiddenTimer = activeTimer();
  visible = false; poller.setVisible(false);
  assert.equal(hiddenTimer.canceled, true);
  hiddenTimer.callback(); await settle();
  assert.equal(pollCount, 2);
  visible = true; poller.setVisible(true);
  assert.equal(activeTimer().delay, 0);
  activeTimer().callback(); await settle();
  assert.equal(activeTimer().delay, 900);
  poller.refresh();
  assert.equal(activeTimer().delay, 0);
  activeTimer().callback(); await settle();
  assert.equal(pollCount, 4);
  poller.stop();
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run([node, "-e", poller_source + harness], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_dashboard_api_fetch_has_bounded_request_timeout() -> None:
    api_fetch = DASHBOARD_HTML[DASHBOARD_HTML.index("async function apiFetch") : DASHBOARD_HTML.index("function setFrontendVisionCaptureState")]
    assert "AbortController" in api_fetch
    assert "setTimeout" in api_fetch
    assert "clearTimeout" in api_fetch


def test_destructive_controls_describe_scope_and_impact_without_remote_control() -> None:
    assert "Restart hub service" not in DASHBOARD_HTML
    assert "Stop hub service" not in DASHBOARD_HTML
    assert "restartHub" not in DASHBOARD_HTML
    assert "stopService" not in DASHBOARD_HTML
    assert "Purge expired cache" in DASHBOARD_HTML
    assert "Scope and impact" in DASHBOARD_HTML
    assert "function openControlConfirmation" in DASHBOARD_HTML


def test_reliability_summary_footer_padding_and_severity_contract() -> None:
    assert 'class="reliability-footer"' in DASHBOARD_HTML
    assert 'id="reliabilityTrend"' in DASHBOARD_HTML
    assert 'id="reliabilityAction"' in DASHBOARD_HTML
    footer_idx = DASHBOARD_HTML.index('class="reliability-footer"')
    trend_idx = DASHBOARD_HTML.index('id="reliabilityTrend"')
    action_idx = DASHBOARD_HTML.index('id="reliabilityAction"')
    assert footer_idx < trend_idx < action_idx
    assert "health=dashboardHealth(snapshot||{})" in DASHBOARD_HTML
    assert "Historical failures and unclean exits describe past events" in DASHBOARD_HTML


def test_dashboard_does_not_rewrite_failed_events_as_successful() -> None:
    assert 'id="resolveErrorsBtn"' not in DASHBOARD_HTML
    assert 'id="resolveAllErrorsBtn"' not in DASHBOARD_HTML
    assert 'function renderResolveErrorsModal(r)' not in DASHBOARD_HTML
    assert "/api/maintenance/resolve_errors" not in DASHBOARD_HTML



def test_dashboard_ux_refinements_and_empty_states() -> None:
    # 1. Control popover & buttons
    assert "Pause live events" in DASHBOARD_HTML
    assert ".control-popover .tiny.muted" in DASHBOARD_HTML
    # 2. Toolbar select dark theme
    assert ".toolbar select" in DASHBOARD_HTML
    # 3. Live events header row
    assert 'class="event-header"' in DASHBOARD_HTML
    assert "Action / Stage" in DASHBOARD_HTML
    # 4. Styled empty table state
    assert "No active items recorded" in DASHBOARD_HTML
    # 5. Worktrees toolbar
    assert 'list="worktreeRoots"' in DASHBOARD_HTML
    assert 'Choose or enter repository root' in DASHBOARD_HTML
    # 6. Reliability tab auto-tail
    assert "if(tabId==='reliability')loadLogsTail();" in DASHBOARD_HTML
    # 7. Bundles table wrap
    assert '<div class="table-wrap"><table><thead><tr><th>Repository identity</th>' in DASHBOARD_HTML


def test_trajectory_inspector_uses_bounded_cursor_pages() -> None:
    assert 'id="trajEventPager"' in DASHBOARD_HTML
    assert "trajectorySnapshotSeq=null" in DASHBOARD_HTML
    assert "stream_id:taskId" in DASHBOARD_HTML
    assert "after_seq:String(trajectoryAfterSeq)" in DASHBOARD_HTML
    assert "query.set('through_seq',String(trajectorySnapshotSeq))" in DASHBOARD_HTML
    assert "(r.ok||r.status===413)&&trajectorySnapshotSeq===null&&Number.isFinite(Number(d.last_seq))" in DASHBOARD_HTML
    assert "evs.filter(ev=>Number(ev.seq||0)<=trajectorySnapshotSeq)" in DASHBOARD_HTML
    assert "limit:'100'" in DASHBOARD_HTML
    assert "trajectoryAfterSeq=Number(d.next_seq||trajectoryAfterSeq)" in DASHBOARD_HTML
    assert "trajectoryHasMore=Boolean(d.has_more)&&Number(trajectoryAfterSeq)<trajectorySnapshotSeq" in DASHBOARD_HTML
    assert "data-load-traj-more" in DASHBOARD_HTML
    assert "trajectoryGaps.push(...d.gap_ranges)" in DASHBOARD_HTML
    assert "Missing retained events" in DASHBOARD_HTML
    assert "trajectoryPageError?'Retry page':'Load next events'" in DASHBOARD_HTML




def test_dashboard_wires_status_refreshes_through_backoff_poller() -> None:
    assert "const statusPoller=createDashboardStatusPoller(isCurrent=>pollStatus(isCurrent))" in DASHBOARD_HTML
    assert "statusPoller.start()" in DASHBOARD_HTML
    assert "statusPoller.setVisible(visible)" in DASHBOARD_HTML
    assert "setInterval(()=>{if(isVisible)pollStatus();},1000)" not in DASHBOARD_HTML
    assert "statusPoller.refresh()" in DASHBOARD_HTML
