import pytest

from local_ai_hub import mcp_server
from local_ai_hub.operation_contracts import validate_operation_arguments


@pytest.mark.parametrize("arguments", [
    {"task": "Measure three input prompts"},
    {"prompt": "One prompt"},
    {"model": "example"},
    {"timeout_seconds": 60},
    {"cases": [{"prompt": "One prompt"}]},
])
def test_generic_benchmark_rejects_ignored_per_input_arguments(monkeypatch, arguments):
    calls = []
    monkeypatch.setattr(mcp_server.FEATURES, "tasks", True)
    monkeypatch.setattr(mcp_server.FEATURES, "has_any_model", lambda: True)
    monkeypatch.setattr(mcp_server, "detailed_diagnostics_enabled", lambda _config: True)
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *args, **kwargs: calls.append((args, kwargs)) or {"success": True})
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)

    error = validate_operation_arguments("local_ai_task", "benchmark", arguments, features=mcp_server.FEATURES)
    assert error and "benchmark" in error
    response = mcp_server.local_ai_task(action="benchmark", **arguments)
    assert response["success"] is False
    assert "benchmark" in response["error"]
    assert calls == []


def test_generic_benchmark_accepts_no_operation_specific_arguments():
    assert validate_operation_arguments("local_ai_task", "benchmark", {}) is None


def test_generic_benchmark_without_arguments_dispatches_existing_suite(monkeypatch):
    calls = []
    monkeypatch.setattr(mcp_server.FEATURES, "tasks", True)
    monkeypatch.setattr(mcp_server.FEATURES, "has_any_model", lambda: True)
    monkeypatch.setattr(mcp_server, "detailed_diagnostics_enabled", lambda _config: True)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)

    def post(path, payload, **kwargs):
        calls.append((path, payload))
        return {"success": True}

    monkeypatch.setattr(mcp_server.CLIENT, "post", post)
    result = mcp_server.local_ai_task(action="benchmark")

    assert result["success"] is True
    assert calls == [("/api/benchmark", {})]
