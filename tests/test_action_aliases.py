from __future__ import annotations

from local_ai_hub.mcp_server import _normalize_deterministic, _desc_status, _desc_coord, _desc_command
from local_ai_hub.operation_contracts import operation_actions, operation_tool_input_schema, validate_operation_call


def test_only_canonical_action_names_are_published_and_accepted():
    for tool in ("local_ai_repo", "local_ai_task", "local_ai_command", "local_ai_coord"):
        schema = operation_tool_input_schema(tool)
        assert schema["properties"]["action"]["enum"] == list(operation_actions(tool))
    aliases = {
        "local_ai_repo": ("sec", "idx", "review", "ctx"),
        "local_ai_task": ("gen", "rev", "del"),
        "local_ai_command": ("patch", "fix", "repair", "fmt"),
        "local_ai_coord": ("ctx", "compile_ctx", "neg_rec", "mem_put", "task_new"),
    }
    for tool, tool_aliases in aliases.items():
        for alias in tool_aliases:
            rejection = validate_operation_call(tool, {"action": alias, "root": "."})
            assert rejection is not None


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
