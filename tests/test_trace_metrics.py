from __future__ import annotations

from types import SimpleNamespace

from local_ai_hub import http_server
from local_ai_hub.debug_traces import DebugTraceStore
from local_ai_hub.telemetry import TelemetryStore


def test_request_metrics_aggregate_only_matching_inference_usage(tmp_path):
    store = TelemetryStore(tmp_path, flush_interval_seconds=0.01)
    try:
        store.record(
            event_type="inference",
            request_id="request-1",
            trace_id="trace-1",
            cache_hit=True,
            input_tokens=18,
            cache_read_tokens=12,
            output_tokens=7,
            avoided_cloud_tokens=25,
            gross_avoided_cloud_tokens=30,
            net_cloud_token_delta=-20,
        )
        store.record(
            event_type="inference",
            request_id="request-1",
            trace_id="trace-1",
            cache_hit=False,
            input_tokens=5,
            cache_read_tokens=0,
            output_tokens=3,
            avoided_cloud_tokens=0,
            gross_avoided_cloud_tokens=0,
            net_cloud_token_delta=8,
        )
        store.record(
            event_type="http",
            request_id="request-1",
            cache_hit=True,
            input_tokens=900,
            output_tokens=700,
        )
        store.record(
            event_type="inference",
            request_id="request-2",
            cache_hit=True,
            input_tokens=1000,
            output_tokens=1000,
            avoided_cloud_tokens=500,
        )

        assert store.flush(1.0)
        metrics = store.request_metrics("request-1")
    finally:
        store.close()

    assert metrics == {
        "available": True,
        "inference_events": 2,
        "cache_hits": 1,
        "cache_hit_rate": 0.5,
        "input_tokens": 23,
        "cache_read_tokens": 12,
        "output_tokens": 10,
        "avoided_cloud_tokens": 25,
        "gross_avoided_cloud_tokens": 30,
        "net_cloud_token_delta": -12,
    }


def test_request_metrics_marks_missing_or_disabled_data_unavailable(tmp_path):
    store = TelemetryStore(tmp_path / "enabled", flush_interval_seconds=0.01)
    disabled = TelemetryStore(tmp_path / "disabled", enabled=False)
    try:
        assert store.request_metrics("")["available"] is False
        assert store.request_metrics("missing-request")["available"] is False
        assert disabled.request_metrics("request-1")["available"] is False
    finally:
        store.close()
        disabled.close()


def test_trace_metrics_endpoint_joins_by_request_id(tmp_path, monkeypatch):
    traces = DebugTraceStore({"server": {"state_dir": str(tmp_path / "traces")}, "debug_traces": {"enabled": True}})
    telemetry = TelemetryStore(tmp_path / "telemetry", flush_interval_seconds=0.01)
    trace_id = traces.start(
        kind="api_request",
        tenant="test",
        action="/api/reason",
        request_id="request-1",
    )
    telemetry.record(
        event_type="inference",
        request_id="request-1",
        cache_hit=True,
        input_tokens=14,
        cache_read_tokens=9,
        output_tokens=6,
        avoided_cloud_tokens=20,
    )
    assert telemetry.flush(1.0)
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            debug_traces=traces,
            telemetry=telemetry,
            async_jobs=SimpleNamespace(path=tmp_path / "jobs.sqlite3"),
        ),
    )
    mode_api = SimpleNamespace(
        load_operational_mode=lambda *, state_dir: SimpleNamespace(mode="active", degraded=False),
        operational_mode_gate_error=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(http_server, "_operational_mode_api", lambda: mode_api)

    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = f"/api/debug-traces/{trace_id}/metrics"
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {}
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    handler.responses = []
    handler._send = lambda status, data: handler.responses.append((status, data))

    try:
        handler.do_GET()
    finally:
        telemetry.close()

    assert handler.responses[0][0] == 200
    assert handler.responses[0][1]["trace_id"] == trace_id
    assert handler.responses[0][1]["metrics"]["cache_hit_rate"] == 1.0
    assert handler.responses[0][1]["metrics"]["input_tokens"] == 14


def test_trace_detail_http_still_returns_bounded_pages(tmp_path, monkeypatch):
    traces = DebugTraceStore({"server": {"state_dir": str(tmp_path / "traces")}, "debug_traces": {"enabled": True}})
    trace_id = traces.start(kind="api_request", tenant="test", action="/api/reason")
    traces.event(trace_id, "output_delta", {"text": "x" * 6000})
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            debug_traces=traces,
            async_jobs=SimpleNamespace(path=tmp_path / "jobs.sqlite3"),
        ),
    )
    mode_api = SimpleNamespace(
        load_operational_mode=lambda *, state_dir: SimpleNamespace(mode="active", degraded=False),
        operational_mode_gate_error=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(http_server, "_operational_mode_api", lambda: mode_api)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = f"/api/debug-traces/{trace_id}?limit=100&max_bytes=8388608"
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {}
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    handler._reconcile_debug_trace = lambda session: session
    handler.responses = []
    handler._send = lambda status, data: handler.responses.append((status, data))

    handler.do_GET()

    assert handler.responses[0][0] == 200
    assert handler.responses[0][1]["response_bytes"] == len(
        http_server._json_bytes(handler.responses[0][1])
    )
