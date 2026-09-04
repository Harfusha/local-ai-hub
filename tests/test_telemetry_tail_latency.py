from __future__ import annotations

import time

from local_ai_hub.telemetry import TelemetryStore
from local_ai_hub.dashboard import DASHBOARD_HTML


def test_report_exposes_http_action_and_cache_layer_tail_percentiles(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.01)
    try:
        store.record_http(action="/fast", cache_layer="exact", success=True, duration_ms=10)
        store.record_http(action="/slow", cache_layer="miss", success=True, duration_ms=100)
        store.record_http(action="/slow", cache_layer="miss", success=False, duration_ms=1_000)
        store.flush(1)
        report = store.report(1)
    finally:
        store.close()

    actions = {item["action"]: item for item in report["http_tail_latency"]["by_action"]}
    layers = {item["cache_layer"]: item for item in report["http_tail_latency"]["by_cache_layer"]}
    assert actions["/slow"]["p95_duration_ms"] == 1_000.0
    assert actions["/slow"]["failures"] == 1
    assert layers["miss"]["p99_duration_ms"] == 1_000.0


def test_dashboard_has_http_tail_latency_target():
    assert 'id="httpTail"' in DASHBOARD_HTML


def test_process_scope_excludes_pre_start_history(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        started = time.time()
        store.record(event_type="inference", created_at=started - 10, action="old", success=True)
        store.process_started_at = started
        store.record(event_type="inference", created_at=started + 1, action="new", success=True)
        store.flush(1)
        assert store.summary(30, scope="process")["events"] == 1
        assert store.report(30, scope="process")["scope"] == "process"
    finally:
        store.close()


def test_process_scope_exposes_per_agent_tail_slo(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        started = time.time()
        store.process_started_at = started
        store.record_http(agent="cloud-a", action="/fast", created_at=started + 1, success=True, duration_ms=10)
        store.record_http(agent="cloud-a", action="/slow", created_at=started + 2, success=False, duration_ms=1_000)
        store.flush(1)
        report = store.report(30, scope="process")
    finally:
        store.close()

    agents = {item["agent"]: item for item in report["agent_slo"]}
    assert agents["cloud-a"]["p99_duration_ms"] == 1_000.0
    assert agents["cloud-a"]["failure_rate"] == 0.5
