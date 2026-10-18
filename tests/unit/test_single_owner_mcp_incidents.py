"""Public incident transport contracts for a single local owner."""

import asyncio

import pytest


@pytest.mark.parametrize("value", [None, "", False, "former-owner"])
@pytest.mark.parametrize("action", [
    "incident_decision", "negative_knowledge_record", "negative_knowledge_find",
])
def test_mcp_rejects_retired_tenant_before_dispatch(monkeypatch, tmp_path, action, value):
    from local_ai_hub import mcp_server

    calls = []

    async def call_tool(name, arguments, *, convert_result=False):
        calls.append(name)
        return {"success": True}

    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", call_tool)
    _, result = asyncio.run(mcp_server._compact_mcp_call_tool("local_ai_coord", {
        "action": action, "root": str(tmp_path), "tenant": value,
        "fingerprint": {"signature_hash": "example"},
        "record": {"message": "example"}, "query": "example",
    }))
    assert result["success"] is False
    assert result["status_code"] == 400
    assert "tenant" in result["error"]
    assert calls == []


@pytest.mark.parametrize("action", [
    "incident_decision", "negative_knowledge_record", "negative_knowledge_find",
])
def test_incidents_do_not_substitute_current_directory_for_explicit_root(monkeypatch, action):
    from local_ai_hub import mcp_server

    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    result = mcp_server.local_ai_coord(
        action=action, root=".", query="example",
        record={"message": "example"}, fingerprint={"signature_hash": "example"},
    )
    assert result["success"] is False
    assert "root" in result["error"]
