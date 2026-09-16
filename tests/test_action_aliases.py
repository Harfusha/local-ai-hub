from __future__ import annotations

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
    assert _resolve_action("task", "gen") == "generate"
    # Unmapped action passes through unchanged
    assert _resolve_action("command", "run") == "run"


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
    # Timestamp rounded to 1 decimal place
    assert normalized["created_at"] == 1720000000.1


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
