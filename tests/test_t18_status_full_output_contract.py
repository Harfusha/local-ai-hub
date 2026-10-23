"""Readiness replaced the retired full MCP status contract."""
import asyncio
import json
from local_ai_hub import mcp_server
from local_ai_hub.operation_contracts import validate_operation_output
from local_ai_hub.operational_mode import OperationalModeSnapshot


def test_status_readiness_matches_registered_output_contract(monkeypatch):
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _: OperationalModeSnapshot("active", 0, None))
    monkeypatch.setattr(mcp_server.CLIENT, "get", lambda _: {"success": True, "hub_online": True, "version": "test", "ollama_online": True, "scheduler": {}})
    result = asyncio.run(mcp_server.mcp.call_tool("local_ai_status", {"detail": "brief"}))[1]
    assert result["success"] is True
    assert validate_operation_output("local_ai_status", "brief", result) is None


def test_readiness_requires_identity_but_not_optional_diagnostics():
    result = {"success": True, "version": "test", "ollama_online": None, "active_model": None, "degraded": False}
    assert validate_operation_output("local_ai_status", "brief", result) is None
    for field in result:
        incomplete = {key: value for key, value in result.items() if key != field}
        assert validate_operation_output("local_ai_status", "brief", incomplete) is not None


def test_retired_full_status_rejects_before_backend(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("retired full status reached backend")
    monkeypatch.setattr(mcp_server.CLIENT, "get", forbidden)
    result = asyncio.run(mcp_server.mcp.call_tool("local_ai_status", {"detail": "full"}))[1]
    assert result["success"] is False
    assert result["status_code"] == 400
