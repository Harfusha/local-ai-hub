import pytest

from local_ai_hub.http_server import Handler, RequestBodyError, _journal_outcome_success, _response_phase_latency, _telemetry_http_outcome
from local_ai_hub.token_accounting import finalize_tool_accounting


def test_response_phase_latency_reads_only_nonnegative_latency_metadata():
    assert _response_phase_latency({"latency": {"queue_wait_ms": 12.5, "service_ms": -1}}) == {
        "queue_wait_ms": 12.5,
        "service_ms": 0.0,
    }


def test_response_phase_latency_ignores_malformed_metadata():
    assert _response_phase_latency({"latency": "not-an-object"}) == {
        "queue_wait_ms": 0.0,
        "service_ms": 0.0,
    }


def test_terminal_client_result_is_not_stored_as_recovery_failure():
    assert _journal_outcome_success(200, {"success": False, "terminal": True}) is True


@pytest.mark.parametrize("reported_success", [False, True])
def test_outcome_unknown_is_not_counted_as_http_reliability_success(reported_success):
    assert _telemetry_http_outcome(200, {
        "success": reported_success,
        "terminal": True,
        "outcome_unknown": True,
    }) == (False, "outcome_unknown", True)


def test_tool_accounting_accepts_current_signed_event_shape():
    event = finalize_tool_accounting(
        tool_name="local_ai_repo",
        arguments={"action": "search", "root": "C:/repo"},
        response={"success": True},
        measured={"gross_cloud_tokens_avoided_est": 100},
    )
    event.update({"agent": "agent", "created_at": 1.0})

    assert len(event) > 24
    Handler._validate_payload("/api/telemetry/tool-accounting", {"events": [event]})


@pytest.mark.parametrize(("path", "payload", "field"), [
    ("/api/code/symbol", {"root": ".", "symbol": ""}, "symbol"),
    ("/api/code-intelligence/query", {"root": ".", "action": "callers", "query": ""}, "query"),
    ("/api/code/diagnostics", {"root": ".", "path": ""}, "path"),
])
def test_code_requests_reject_empty_required_inputs(path, payload, field):
    with pytest.raises(RequestBodyError, match=field):
        Handler._validate_payload(path, payload)


def test_html_response_records_live_http_completion(monkeypatch):
    from types import SimpleNamespace
    import time

    import local_ai_hub.http_server as http_server

    events = []

    class Telemetry:
        def record_http(self, **event):
            event["event_type"] = "http"
            events.append(event)

    app = SimpleNamespace(
        telemetry=Telemetry(),
        config={"observability": {"exclude_http_paths": []}},
        debug_traces=None,
    )
    monkeypatch.setattr(http_server, "APP", app)

    handler = object.__new__(Handler)
    handler.headers = {}
    handler.command = "GET"
    handler.path = "/"
    handler._trace_request_id = "request-123"
    handler._trace_id = "trace-123"
    handler._request_path = "/"
    handler._request_started = time.perf_counter()
    handler._telemetry_finished = False
    handler._debug_trace_id = ""
    handler.close_connection = False
    handler.wfile = SimpleNamespace(write=lambda body: len(body))
    handler.send_response = lambda _status: None
    handler.send_header = lambda _name, _value: None
    handler.end_headers = lambda: None
    handler._common_headers = lambda **_kwargs: None

    handler._send_html(200, "<html><body>ok</body></html>")

    assert len(events) == 1
    assert events[0]["event_type"] == "http"
    assert events[0]["request_id"] == "request-123"
    assert events[0]["status_code"] == 200
    assert events[0]["response_bytes"] > 0
