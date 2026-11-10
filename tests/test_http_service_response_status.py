import io
import json

import pytest

from local_ai_hub import http_server
from local_ai_hub.deterministic import DeterministicEngine


def test_http_service_response_preserves_explicit_client_error_status():
    handler = object.__new__(http_server.Handler)
    handler.responses = []
    handler._send = lambda status, payload: handler.responses.append((status, payload))
    result = {"success": False, "status_code": 400, "error": "symbol must be a valid Python identifier"}

    http_server.Handler._send_service_result(handler, result)

    assert handler.responses == [(400, result)]


def test_http_service_response_preserves_not_found_status():
    handler = object.__new__(http_server.Handler)
    handler.responses = []
    handler._send = lambda status, payload: handler.responses.append((status, payload))
    result = {"success": False, "status_code": 404, "error": "no SQLite database found"}

    http_server.Handler._send_service_result(handler, result)

    assert handler.responses == [(404, result)]


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


def test_schema_inspect_reports_not_found_status_for_missing_database(tmp_path):
    result = DeterministicEngine().schema_inspect(str(tmp_path))

    assert result["success"] is False
    assert result["status_code"] == 404


def test_explain_query_rejects_empty_query_with_client_error_status(tmp_path):
    db_path = tmp_path / "data.sqlite3"
    db_path.touch()

    result = DeterministicEngine().explain_query(str(tmp_path), "", db_path.name)

    assert result["success"] is False
    assert result["status_code"] == 400


@pytest.mark.parametrize(("days", "limit"), [(0, 20), (30, 0)])
def test_find_hotspots_validation_errors_are_client_errors(tmp_path, days, limit):
    result = DeterministicEngine().find_hotspots(str(tmp_path), days=days, limit=limit)

    assert result["success"] is False
    assert result["status_code"] == 400
    assert result["terminal"] is True
    assert result["retryable"] is False
