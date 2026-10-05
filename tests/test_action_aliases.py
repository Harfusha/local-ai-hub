from __future__ import annotations

import asyncio
import json

import mcp.types as t

from local_ai_hub import mcp_server as local_ai_mcp
from local_ai_hub.mcp_server import _resolve_action, _normalize_deterministic, _desc_status, _desc_coord, _desc_command


def test_action_aliases_resolution():
    assert _resolve_action("coord", "ctx") == "context_compile"
    assert _resolve_action("coord", "neg_rec") == "negative_knowledge_record"
    assert _resolve_action("coord", "neg_find") == "negative_knowledge_find"
    assert _resolve_action("coord", "mem_put") == "memory_record"
    assert _resolve_action("coord", "mem_get") == "memory_get"
    assert _resolve_action("coord", "task_new") == "task_create"
    assert _resolve_action("command", "patch") == "patch_and_verify"
    assert _resolve_action("command", "fix") == "auto_fix"
    assert _resolve_action("command", "repair") == "repair_loop"
    assert _resolve_action("command", "fmt") == "format"
    assert _resolve_action("repo", "idx") == "code_index"
    assert _resolve_action("repo", "review") == "review_diff"
    assert _resolve_action("task", "gen") == "delegate"
    assert _resolve_action("task", "explore") == "explore"
    # Unmapped action passes through unchanged
    assert _resolve_action("command", "run") == "run"


def test_mcp_protocol_call_dispatches_coord_task_new_alias(monkeypatch):
    class RecordingCoordClient:
        def __init__(self):
            self.calls = []

        def coord(self, **kwargs):
            self.calls.append(kwargs)
            return {"success": True}

    client = RecordingCoordClient()
    monkeypatch.setattr(local_ai_mcp, "CLIENT", client)

    request = t.CallToolRequest(
        method="tools/call",
        params=t.CallToolRequestParams(
            name="local_ai_coord",
            arguments={"action": "task_new", "task": "fixture task"},
        ),
    )
    result = asyncio.run(
        local_ai_mcp.mcp._mcp_server.request_handlers[t.CallToolRequest](request)
    )

    assert hasattr(result, "root")
    tool_result = result.root
    assert isinstance(tool_result, t.CallToolResult)
    assert len(tool_result.content) >= 1
    content = tool_result.content[0]
    assert isinstance(content, t.TextContent)
    assert json.loads(content.text)["success"] is True
    assert len(client.calls) == 1
    assert client.calls[0]["action"] == "task_create"
    assert client.calls[0]["task"] == "fixture task"


def test_normalize_deterministic_keys_and_timestamps():
    data = {
        "z_key": 1,
        "a_key": 2,
        "created_at": 1720000000.123456,
        "nested": {
            "m": 3,
            "b": 4,
        },
    }
    normalized = _normalize_deterministic(data)
    keys = list(normalized.keys())
    assert keys == ["a_key", "created_at", "nested", "z_key"]
    nested_keys = list(normalized["nested"].keys())
    assert nested_keys == ["b", "m"]
    # Cache/debug payloads retain exact timestamps; only dict ordering is normalized.
    assert normalized["created_at"] == 1720000000.123456


def test_lean_schemas_concise_descriptions():
    desc_status = _desc_status()
    assert len(desc_status.splitlines()) == 1
    assert "Health" in desc_status

    desc_coord = _desc_coord()
    assert len(desc_coord.splitlines()) == 1
    assert "Agent OS coordination" in desc_coord

    desc_command = _desc_command()
    assert len(desc_command.splitlines()) == 1
    assert "Safe CLI command broker" in desc_command
