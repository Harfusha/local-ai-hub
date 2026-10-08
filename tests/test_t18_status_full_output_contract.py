import asyncio
import json

from local_ai_hub import mcp_server
from local_ai_hub.operation_contracts import validate_operation_output


def test_t18_full_status_matches_generic_object_output_contract(monkeypatch) -> None:
    def fake_get(path: str):
        if path.startswith("/api/status") or path.startswith("/api/live/status"):
            return {"success": True, "hub_online": True, "version": "test", "scheduler": {}, "observability": {}}
        if path == "/api/capabilities":
            return {"features": {}}
        raise AssertionError(f"unexpected status request: {path}")

    monkeypatch.setattr(mcp_server.CLIENT, "get", fake_get)

    tool_result = asyncio.run(mcp_server.mcp.call_tool("local_ai_status", {"action": "full"}))
    content = tool_result[0][0] if isinstance(tool_result, tuple) else tool_result[0]
    result = json.loads(content.text)

    schema = mcp_server.mcp._tool_manager._tools["local_ai_status"].output_schema
    assert schema.get("type") == "object"
    assert isinstance(result, dict)
    assert result["success"] is True
    assert validate_operation_output("local_ai_status", "full", result) is None


def test_full_status_requires_identity_but_not_optional_diagnostics() -> None:
    result = {"success": True, "hub_online": True, "version": "test"}
    assert validate_operation_output("local_ai_status", "full", result) is None
    for field in ("success", "hub_online", "version"):
        incomplete = {key: value for key, value in result.items() if key != field}
        assert validate_operation_output("local_ai_status", "full", incomplete) is not None
