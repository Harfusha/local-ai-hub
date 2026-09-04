from __future__ import annotations

from local_ai_hub.telemetry import TelemetryStore


def test_report_counts_metadata_only_cache_decisions(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.01)
    try:
        store.record_stage(
            action="delegate:review",
            stage="cache_decision",
            error_type="new_exact_key",
            success=True,
        )
        store.flush(1)
        report = store.report(1)
    finally:
        store.close()

    assert report["cache_decisions"] == {"new_exact_key": 1}
