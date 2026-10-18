"""Deferred F24 regression coverage; pure task objects, no persistent state."""

from types import SimpleNamespace

import pytest

from local_ai_hub.agent_tasks import CompletionGateError, TaskStore
from local_ai_hub.operation_contracts import operation_parameters_schema


def _task(audit=None):
    state = {
        "memory_context": {
            "schema_version": 2,
            "context": {
                "root": "C:/repo",
                "coordination_id": "repo-coordination",
                "task_id": "task-audit",
                "session_id": "",
                "clone_id": "",
                "worktree_id": "",
                "branch": "",
            },
            "items": [{"id": "relevant"}],
            "warnings": [],
        }
    }
    if audit is not None:
        state["memory_audit"] = audit
    return SimpleNamespace(task_id="task-audit", checkpoint=SimpleNamespace(state_data=state))


def test_checkpoint_error_names_required_nested_field_without_false_transition():
    with pytest.raises(CompletionGateError) as caught:
        TaskStore._validate_memory_audit(_task())
    assert "state_data.memory_audit" in str(caught.value)
    assert "COMPLETED" not in str(caught.value)


def test_irrelevant_memory_reason_is_accepted_without_claiming_use():
    TaskStore._validate_memory_audit(
        _task({"used_ids": [], "not_used_reason": "Supplied item is unrelated."})
    )


def test_unknown_memory_ids_still_fail():
    with pytest.raises(CompletionGateError, match="unavailable memory IDs"):
        TaskStore._validate_memory_audit(_task({"used_ids": ["invented"]}))


def test_published_checkpoint_schema_describes_nested_memory_audit():
    schema = operation_parameters_schema("local_ai_coord")
    checkpoint = schema["properties"]["checkpoint"]
    audit = checkpoint["properties"]["state_data"]["properties"]["memory_audit"]
    assert set(audit["properties"]) == {"used_ids", "not_used_reason", "source_checks"}
    assert "every checkpoint" in checkpoint["description"]
