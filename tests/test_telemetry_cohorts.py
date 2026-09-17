from __future__ import annotations

from local_ai_hub.telemetry import TelemetryStore


def test_summary_keeps_agent_http_and_inference_percentiles_separate(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.01)
    try:
        store.record_http(action="/api/repo/search", agent="codex", success=True, duration_ms=8)
        store.record(event_type="inference", action="delegate:review", success=True, duration_ms=8_000)
        store.flush(1)
        summary = store.summary(1)
    finally:
        store.close()

    assert summary["cohorts"]["agent_http"]["p95_duration_ms"] == 8
    assert summary["cohorts"]["inference"]["p95_duration_ms"] == 8_000


def test_summary_aggregate_percentiles_match_inference_event_population(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.01)
    try:
        for _ in range(20):
            store.record_http(action="/api/repo/search", agent="codex", success=True, duration_ms=40_000)
        store.record(event_type="inference", action="delegate:review", success=True, duration_ms=8_000)
        store.flush(1)
        summary = store.summary(1)
    finally:
        store.close()

    assert summary["events"] == 1
    assert summary["aggregate_duration_scope"] == "inference_only"
    assert summary["p95_duration_ms"] == 8_000
    assert summary["p99_duration_ms"] == 8_000


def test_summary_labels_policy_block_separately_from_operational_failure(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.01)
    try:
        store.record_http(action="/api/command", success=True, status_code=400, error_type="policy_block")
        store.record_http(action="/api/repo/search", success=False, status_code=503, error_type="http_error")
        store.flush(1)
        summary = store.summary(1)
    finally:
        store.close()

    assert summary["cohorts"]["policy_rejection"]["events"] == 1
    assert summary["cohorts"]["agent_http"]["failures"] == 1


def test_realtime_summary_exposes_agent_and_inference_cohorts(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.01)
    try:
        store.record_http(action="/api/repo/search", success=True, duration_ms=5)
        store.record(event_type="inference", success=True, duration_ms=500)
        store.flush(1)
        live = store.realtime_summary(scope="process")
    finally:
        store.close()

    assert set(live["cohorts"]) >= {"agent_http", "inference"}
    assert live["scope"] == "process"
    assert live["process_started_at"] == store.process_started_at


def test_telemetry_resolve_errors_clears_failures_crashes_and_errors(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.01)
    try:
        store.record_http(action="/api/repo/search", success=False, status_code=500, error_type="http_error")
        store.record_error("repo", "search", RuntimeError("failed"))
        store.flush(1)
        summary_before = store.summary(1)
        assert summary_before["cohorts"]["agent_http"]["failures"] == 1

        res = store.resolve_errors()
        assert res["success"] is True
        assert res["resolved_events"] >= 1
        assert res["cleared_errors"] >= 1

        summary_after = store.summary(1)
        assert summary_after["cohorts"]["agent_http"]["failures"] == 0
        rep = store.report(1)
        assert len(rep.get("recent_errors", [])) == 0
    finally:
        store.close()

