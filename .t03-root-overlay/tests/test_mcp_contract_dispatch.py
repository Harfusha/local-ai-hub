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


def test_mcp_dispatch_rejects_malformed_repo_search_hit(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    async def fake_call_tool(_name, _arguments, *, convert_result=False):
        return {
            "success": True,
            "root": "C:/repo",
            "results": [{
                "path": 17,
                "start_line": "line one",
                "end_line": 3,
                "score": 4.5,
                "text": "needle",
            }],
        }

    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fake_call_tool)
    _content, payload = asyncio.run(
        mcp_server._compact_mcp_call_tool(
            "local_ai_repo",
            {"action": "search", "root": "C:/repo", "query": "needle"},
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
    assert output_schema["additionalProperties"] is True
    assert "anyOf" not in output_schema
    assert output_schema["properties"]["success"]["type"] == "boolean"
    assert output_schema["properties"]["status"]["type"] == "string"


def test_registered_status_output_catalog_uses_brief_contract_not_aliases() -> None:
    from local_ai_hub import mcp_server
    from local_ai_hub.operation_contracts import operation_tool_output_schema

    registered = mcp_server.mcp._tool_manager._tools["local_ai_status"]
    output_schema = registered.output_schema
    expected = operation_tool_output_schema("local_ai_status", mcp_server.FEATURES)

    assert output_schema == expected
    assert "brief" in output_schema["x-action-output-contracts"]
    assert not {"status", "health", "check", "info"} & set(
        output_schema["x-action-output-contracts"]
    )
    assert "brief" in registered.parameters["properties"]["detail"]["enum"]


def test_live_mcp_schemas_match_registry_for_every_public_tool() -> None:
    from local_ai_hub import mcp_server
    from local_ai_hub.operation_contracts import (
        OPERATION_CONTRACTS,
        operation_tool_input_schema,
        operation_tool_output_schema,
    )

    registered = mcp_server.mcp._tool_manager._tools
    wire_tools = {tool.name: tool for tool in asyncio.run(mcp_server.mcp.list_tools())}
    assert set(wire_tools) == set(OPERATION_CONTRACTS)

    for name in OPERATION_CONTRACTS:
        expected_input = operation_tool_input_schema(name, mcp_server.FEATURES)
        expected_output = operation_tool_output_schema(name, mcp_server.FEATURES)
        assert registered[name].parameters == expected_input, name
        assert wire_tools[name].inputSchema == expected_input, name
        assert registered[name].output_schema == expected_output, name
        assert wire_tools[name].outputSchema == expected_output, name
