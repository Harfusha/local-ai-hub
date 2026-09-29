from __future__ import annotations

import asyncio

def test_mcp_dispatch_rejects_unknown_arguments_before_http_tool_call(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    calls: list[str] = []

    async def fake_call_tool(name, arguments, *, convert_result=False):
        calls.append(name)
        return {"success": True}

    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fake_call_tool)

    _content, payload = asyncio.run(
        mcp_server._compact_mcp_call_tool(
            "local_ai_status",
            {"action": "brief", "unknown_argument": True},
        )
    )

    assert payload["success"] is False
    assert payload["status_code"] == 400
    assert "unknown_argument" in payload["error"]
    assert calls == []


def test_mcp_dispatch_rejects_artifact_list_get_fields_before_tool_call(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    calls: list[str] = []

    async def fake_call_tool(name, arguments, *, convert_result=False):
        calls.append(name)
        return {"success": True}

    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fake_call_tool)

    _content, payload = asyncio.run(
        mcp_server._compact_mcp_call_tool(
            "local_ai_artifact",
            {"action": "list", "artifact_id": "artifact-1"},
        )
    )

    assert payload["success"] is False
    assert payload["status_code"] == 400
    assert "artifact_id" in payload["error"]
    assert calls == []


def test_mcp_dispatch_rejects_invalid_output_envelope(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    async def fake_call_tool(_name, _arguments, *, convert_result=False):
        return {"success": "yes"}

    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fake_call_tool)

    _content, payload = asyncio.run(
        mcp_server._compact_mcp_call_tool(
            "local_ai_status",
            {"action": "brief"},
        )
    )

    assert payload["success"] is False
    assert payload["status_code"] == 500
    assert "output contract" in payload["error"]


def test_mcp_dispatch_rejects_invalid_artifact_list_item_shape(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    async def fake_call_tool(_name, _arguments, *, convert_result=False):
        return {"success": True, "artifacts": [{"artifact_id": "artifact-1"}]}

    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fake_call_tool)

    _content, payload = asyncio.run(
        mcp_server._compact_mcp_call_tool(
            "local_ai_artifact", {"action": "list"}
        )
    )

    assert payload["success"] is False
    assert payload["status_code"] == 500
    assert "output contract" in payload["error"]


def test_live_mcp_schema_publishes_action_conditions_and_output_schema() -> None:
    from local_ai_hub import mcp_server

    registered = mcp_server.mcp._tool_manager._tools["local_ai_artifact"]
    input_schema = registered.parameters
    output_schema = registered.output_schema

    assert "allOf" in input_schema
    assert any(
        branch.get("then", {}).get("required") == ["action", "artifact_id"]
        for branch in input_schema["allOf"]
    )
    assert output_schema["type"] == "object"
    assert output_schema["anyOf"]
    assert all(
        branch["properties"]["success"]["type"] == "boolean"
        for branch in output_schema["anyOf"]
    )
