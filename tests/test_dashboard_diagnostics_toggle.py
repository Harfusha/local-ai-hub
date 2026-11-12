from local_ai_hub.dashboard import DASHBOARD_HTML


def test_detailed_telemetry_toggle_exposes_failed_update_feedback():
    assert 'id="detailedTelemetryStatus" class="tiny" role="status" aria-live="polite"' in DASHBOARD_HTML

    handler = DASHBOARD_HTML.split(
        "if($('detailedTelemetryToggle'))$('detailedTelemetryToggle').onclick=async()=>{",
        1,
    )[1].split("\n};", 1)[0]
    assert "Could not confirm telemetry change. Check the displayed state before retrying." in handler
