import pytest

from local_ai_hub.telemetry import TelemetryStore


@pytest.mark.parametrize("scope", ["window", "process"])
def test_report_window_events_count_all_recorded_event_types(tmp_path, scope):
    store = TelemetryStore(tmp_path)
    try:
        store.record(event_type="inference", success=True, duration_ms=1)
        store.record_http(action="/api/example", success=True, duration_ms=2)
        assert store.flush(2)
        report = store.report(days=1, scope=scope)
        assert report["counts"]["events"] == 2
        assert report["window"]["events"] == 2
        assert report["window"]["inference_events"] == 1
        assert report["summary"]["events"] == 1
    finally:
        store.close()
