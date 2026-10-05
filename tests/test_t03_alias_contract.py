from __future__ import annotations

import asyncio


def test_mcp_action_alias_schema_and_dispatch_use_canonical_contract(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    schema = mcp_server._mcp_contract_schema("local_ai_coord")
    action_schema = schema["properties"]["action"]
    assert "task_new" in action_schema["enum"]
    assert "task_new" in mcp_server.CoordAction.__args__
    contract_rule = next(
        branch for branch in schema["allOf"]
        if "task_create"
        in branch.get("if", {}).get("properties", {}).get("action", {}).get("enum", [])
    )
    action_enum = contract_rule["if"]["properties"]["action"]["enum"]
    assert "task_new" in action_enum

    validated: list[dict[str, object]] = []
    dispatched: list[dict[str, object]] = []

    def validate_call(arguments, _schema):
        validated.append(arguments)
        return None

    async def fake_call_tool(_name, arguments, *, convert_result=False):
        dispatched.append(arguments)
        return {"success": True}

    monkeypatch.setattr(mcp_server, "validate_schema_object", validate_call)
    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fake_call_tool)
    _content, payload = asyncio.run(mcp_server._compact_mcp_call_tool(
        "local_ai_coord", {"action": "task_new", "task": "alias contract"}
    ))

    assert payload["success"] is True
    assert validated[0]["action"] == "task_create"
    assert dispatched[0]["action"] == "task_new"
