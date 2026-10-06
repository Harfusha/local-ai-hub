from __future__ import annotations

import asyncio


def test_mcp_action_alias_schema_and_dispatch_use_canonical_contract(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    schema = mcp_server.mcp._tool_manager._tools["local_ai_coord"].parameters
    action_schema = schema["properties"]["action"]
    assert "task_new" in action_schema["enum"]
    assert "task_new" in mcp_server.CoordAction.__args__
    contract_rules = [
        branch for branch in schema.get("allOf", [])
        if branch.get("if", {}).get("properties", {}).get("action", {}).get("const") == "task_create"
    ]
    alias_rules = [
        branch for branch in schema.get("allOf", [])
        if branch.get("if", {}).get("properties", {}).get("action", {}).get("const") == "task_new"
    ]
    expected_alias_rules = []
    for branch in contract_rules:
        expected = {**branch, "if": {**branch["if"], "properties": {"action": {"const": "task_new"}}}}
        expected_alias_rules.append(expected)
    assert alias_rules == expected_alias_rules

    validated: list[dict[str, object]] = []
    dispatched: list[dict[str, object]] = []

    def validate_call(_name, arguments, *, features=None):
        validated.append(dict(arguments))
        return None

    def validate_output(_name, action, _value):
        dispatched.append({"output_action": action})
        return None

    async def fake_call_tool(_name, arguments, *, convert_result=False):
        dispatched.append(arguments)
        return {"success": True}

    monkeypatch.setattr(mcp_server, "validate_operation_call", validate_call)
    monkeypatch.setattr(mcp_server, "validate_operation_output", validate_output)
    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fake_call_tool)
    _content, payload = asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_coord", {"action": "task_new", "task": "alias contract"}
    ))

    assert payload["success"] is True
    assert validated[0]["action"] == "task_create"
    assert dispatched[0]["action"] == "task_new"
    assert dispatched[1]["output_action"] == "task_create"
