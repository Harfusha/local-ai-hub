import asyncio
import json

from local_ai_hub import mcp_server


def test_t18_full_status_matches_generic_object_output_contract(monkeypatch) -> None:
    def fake_get(path: str):
        if path.startswith("/api/live/status"):
            return {"hub_online": True, "version": "test", "scheduler": {}, "observability": {}}
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
