import io
import json

from local_ai_hub import http_server


def test_wire_response_does_not_return_http_200_for_application_failure(monkeypatch):
    monkeypatch.setattr(http_server, "APP", None)
    handler = object.__new__(http_server.Handler)
    handler.path = "/api/repo/hotspots"
    handler.command = "POST"
    handler.headers = {}
    handler.wfile = io.BytesIO()
    statuses = []
    handler.send_response = statuses.append
    handler.send_header = lambda *_args: None
    handler.end_headers = lambda: None
    handler._common_headers = lambda: None
    handler._finish_debug_trace = lambda *_args: None
    handler._close_trace_context = lambda: None
    handler._debug_trace_finished = True
    handler._telemetry_finished = True

    http_server.Handler._send(handler, 200, {
        "success": False,
        "error": "unexpected failure",
        "retryable": False,
    })

    payload = json.loads(handler.wfile.getvalue())
    assert statuses == [500]
    assert payload["success"] is False
    assert payload["status_code"] == 500
    assert payload["terminal"] is True
    assert payload["retryable"] is False
