from local_ai_hub.dashboard import DASHBOARD_HTML


def test_detailed_telemetry_toggle_exposes_failed_update_feedback():
    assert 'id="detailedTelemetryStatus" class="tiny" role="status" aria-live="polite"' in DASHBOARD_HTML

    handler = DASHBOARD_HTML.split(
        "if($('detailedTelemetryToggle'))$('detailedTelemetryToggle').onclick=async()=>{",
        1,
    )[1].split("\n};", 1)[0]
    assert "Could not confirm telemetry change. Check the displayed state before retrying." in handler
    assert "result?.failure_stage==='persistence'" in handler
    assert "result?.failure_stage==='validation'" in handler
    assert "Telemetry update failed${stageText}: ${message}" in handler
    assert "const displayedState=button?.getAttribute('aria-pressed')" in handler
    assert "displayedState==='true'?false:displayedState==='false'?true" in handler
    assert "await confirmDetailedTelemetryEnable()" in handler
    assert 'id="detailedTelemetryConfirm"' in DASHBOARD_HTML


def test_stale_status_poll_does_not_revert_successful_live_toggle():
    handler = DASHBOARD_HTML.split(
        "if($('detailedTelemetryToggle'))$('detailedTelemetryToggle').onclick=async()=>{",
        1,
    )[1].split("\n};", 1)[0]

    assert "let detailedTelemetryOverride=null;" in DASHBOARD_HTML
    assert "detailedTelemetryOverride=enabled;" in handler
    assert "resolveDetailedTelemetryState(Boolean(s.debug_traces?.enabled))" in DASHBOARD_HTML
    assert "if(detailedTelemetryOverride===null||reported===detailedTelemetryOverride)" in DASHBOARD_HTML
