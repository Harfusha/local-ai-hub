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
