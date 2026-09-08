from local_ai_hub.delivery import decide_delivery
from local_ai_hub.telemetry import TelemetryStore
from local_ai_hub import http_server


def test_auto_delivery_uses_async_when_observed_p95_exceeds_budget():
    decision = decide_delivery("auto", latency_budget_ms=5_000, observed_p95_ms=5_001, samples=20)

    assert decision == {
        "mode": "async",
        "reason": "p95_latency_budget_exceeded",
        "observed_p95_ms": 5_001.0,
        "samples": 20,
    }


def test_auto_delivery_stays_sync_without_enough_history():
    decision = decide_delivery("auto", latency_budget_ms=5_000, observed_p95_ms=9_000, samples=3)

    assert decision["mode"] == "sync"
    assert decision["reason"] == "insufficient_latency_history"


def test_sync_is_default_even_when_tail_is_high():
    decision = decide_delivery("sync", latency_budget_ms=1, observed_p95_ms=9_000, samples=100)

    assert decision["mode"] == "sync"
    assert decision["reason"] == "sync_requested"


def test_http_latency_estimate_uses_bounded_endpoint_history(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.01)
    try:
        store.record_http(action="/api/reason", duration_ms=100)
        store.record_http(action="/api/reason", duration_ms=200)
        store.flush(1)
        assert store.http_latency_estimate("/api/reason") == {"samples": 2, "p95_duration_ms": 200.0}
    finally:
        store.close()


def test_async_delivery_maps_reason_payload_to_the_existing_job_contract(monkeypatch):
    submitted = {}

    class _Telemetry:
        def http_latency_estimate(self, _action):
            return {"samples": 12, "p95_duration_ms": 9_000}

    class _Jobs:
        def submit(self, tenant, action, payload):
            submitted.update(tenant=tenant, action=action, payload=payload)
            return {"success": True, "job_id": "job-1", "state": "queued"}

    class _App:
        telemetry = _Telemetry()
        async_jobs = _Jobs()

    monkeypatch.setattr(http_server, "APP", _App())
    handler = object.__new__(http_server.Handler)
    status, response = handler._async_delivery(
        "/api/reason", {"delivery": "auto", "latency_budget_ms": 5_000, "problem": "find cause", "context": "facts"}, "tenant-a"
    )

    assert status == 200
    assert response["delivery"]["reason"] == "p95_latency_budget_exceeded"
    assert submitted == {"tenant": "tenant-a", "action": "reason", "payload": {"problem": "find cause", "context": "facts", "task": "find cause"}}
