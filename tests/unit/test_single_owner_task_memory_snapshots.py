"""One canonical task-memory snapshot with explicit namespaces."""

from types import SimpleNamespace

import pytest

from local_ai_hub.agent_consistency import AgentConsistencyGuard, ConsistencyRequest
from local_ai_hub.agent_tasks import CompletionGateError, TaskStore
from local_ai_hub.token_accounting import json_tokens
from local_ai_hub.task_memory_wire import task_memory_projection


def _snapshot():
    return {
        "schema_version": 2,
        "context": {
            "root": "", "coordination_id": "", "task_id": "task-one", "session_id": "chat-one",
            "clone_id": "", "worktree_id": "", "branch": "",
        },
        "instruction": "Cite memory IDs or explain non-use.",
        "items": [{"id": "memory-one", "content": "Useful evidence", "volatile": False}],
        "warnings": [], "estimated_tokens": 0,
    }


def _task(snapshot, audit=None):
    return SimpleNamespace(task_id="task-one", checkpoint=SimpleNamespace(state_data={
        "memory_context": snapshot, "memory_audit": audit,
    }))


def test_warning_snapshot_has_no_owner_partition():
    snapshot = TaskStore._memory_warning("memory_lookup_busy")
    assert snapshot["schema_version"] == 2
    assert snapshot["context"] == {}
    assert "tenant_key" not in snapshot
    assert json_tokens(snapshot) <= 512


@pytest.mark.parametrize("version", [1, True, 2.0, "2", None])
def test_previous_snapshot_contract_is_not_accepted_or_translated(version):
    snapshot = _snapshot()
    snapshot["schema_version"] = version
    with pytest.raises(ValueError, match="offline conversion"):
        TaskStore._fit_memory_snapshot(snapshot)
    with pytest.raises(CompletionGateError, match="offline conversion"):
        TaskStore._validate_memory_audit(_task(snapshot))


def test_retired_partition_key_rejects_even_null():
    snapshot = _snapshot()
    snapshot["tenant_key"] = None
    with pytest.raises(ValueError, match="offline conversion"):
        TaskStore._fit_memory_snapshot(snapshot)


def test_valid_snapshot_keeps_task_session_and_budget():
    snapshot = TaskStore._fit_memory_snapshot(_snapshot())
    assert snapshot["context"]["task_id"] == "task-one"
    assert snapshot["context"]["session_id"] == "chat-one"
    assert json_tokens(snapshot) <= 512
    TaskStore._validate_memory_audit(_task(snapshot, {"used_ids": ["memory-one"]}))


def test_snapshot_for_other_task_rejects():
    snapshot = _snapshot()
    snapshot["context"]["task_id"] = "other-task"
    with pytest.raises(CompletionGateError, match="identity"):
        TaskStore._validate_memory_audit(_task(snapshot, {"used_ids": ["memory-one"]}))


def test_wire_projection_preserves_snapshot_context():
    snapshot = _snapshot()
    projected = task_memory_projection({"task": {"task_id": "task-one", "checkpoint": {
        "state_data": {"memory_context": snapshot},
    }}})
    bundle = projected["task"]["checkpoint"]["state_data"]["memory_context"]
    assert bundle["context"] == snapshot["context"]
    assert "tenant_key" not in bundle


def test_wire_does_not_translate_retired_snapshot():
    with pytest.raises(ValueError, match="offline conversion"):
        task_memory_projection({"task": {"checkpoint": {"state_data": {
            "memory_context": {"schema_version": 1, "tenant_key": None, "items": []},
        }}}})


def test_memory_ids_still_require_audit_and_current_membership():
    with pytest.raises(CompletionGateError, match="memory_audit"):
        TaskStore._validate_memory_audit(_task(_snapshot()))
    with pytest.raises(CompletionGateError, match="unavailable memory IDs"):
        TaskStore._validate_memory_audit(_task(_snapshot(), {"used_ids": ["other-memory"]}))


@pytest.mark.parametrize("value", [None, "", False, "former-owner"])
def test_consistency_request_rejects_retired_identity(tmp_path, value):
    with pytest.raises(TypeError, match="tenant"):
        ConsistencyRequest(root=str(tmp_path), tenant=value)
    with pytest.raises(ValueError, match="retired"):
        ConsistencyRequest.from_dict({"root": str(tmp_path), "tenant": value})


def test_guard_does_not_publish_retired_metadata_using_root_fallback(tmp_path):
    stored = []
    guard = AgentConsistencyGuard(
        SimpleNamespace(config={}), memory_store=SimpleNamespace(record=lambda *args, **kwargs: stored.append(args)),
    )
    guard._record_memory("fact", {"root": str(tmp_path), "tenant": None}, root=str(tmp_path), stable_key="fact", value="value")
    assert stored == []
