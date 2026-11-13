"""One canonical task-memory snapshot with explicit namespaces."""

from types import SimpleNamespace

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_consistency import AgentConsistencyGuard, ConsistencyRequest
from local_ai_hub.agent_tasks import (
    CheckpointResponseBudgetError,
    CompletionGateError,
    GoalContract,
    TaskCheckpoint,
    TaskStatus,
    TaskStore,
)
from local_ai_hub.token_accounting import json_tokens
from local_ai_hub.task_memory_wire import task_memory_projection, task_memory_wire_tokens, task_private_state_projection


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


def test_wire_projection_preserves_resumable_checkpoint_with_memory():
    checkpoint = {
        "phase": "verification",
        "next_action": "inspect result",
        "affected_paths": ["README.md"],
        "evidence_ids": ["evidence-1"],
        "blockers": ["pending review"],
        "state_data": {"memory_context": _snapshot(), "roundtrip_marker": {"value": 7}},
    }
    result = {"success": True, "task": {"task_id": "task-one", "checkpoint": checkpoint}}

    projected = task_memory_projection(result)
    assert projected["task"]["checkpoint"] == checkpoint
    assert task_memory_projection(projected)["task"]["checkpoint"] == checkpoint


def test_private_wire_projection_omits_file_snapshots_but_preserves_other_state():
    value = {"success": True, "task": {"task_id": "task-one", "status": "active", "checkpoint": {
        "phase": "editing", "state_data": {
            "file_snapshots": {"C:/repo/secret.txt": "before image"},
            "roundtrip_marker": {"value": 7},
        },
    }}}

    projected = task_private_state_projection(value)

    state = projected["task"]["checkpoint"]["state_data"]
    assert "file_snapshots" not in state
    assert state["roundtrip_marker"] == {"value": 7}
    assert projected["task"]["checkpoint"]["state_data_omitted"] == ["file_snapshots"]


def test_wire_budget_accounts_for_checkpoint_state_data():
    checkpoint = {"phase": "verification", "state_data": {"memory_context": _snapshot()}}
    small = {"success": True, "task": {"task_id": "task-one", "checkpoint": checkpoint}}
    large = {"success": True, "task": {"task_id": "task-one", "checkpoint": {
        "phase": "verification", "state_data": {"memory_context": _snapshot(), "marker": "x" * 12000},
    }}}

    assert task_memory_wire_tokens(large, 512) > 512
    assert task_memory_wire_tokens(large, 8192) > task_memory_wire_tokens(small, 8192)


def test_wire_projection_keeps_memory_audit_sanitized():
    value = {"task": {"checkpoint": {"state_data": {
        "memory_context": _snapshot(),
        "memory_audit": {"used_ids": ["memory-one"], "history": "private"},
        "memory_audit_history": [{"content": "private history"}],
        "_pending_fenced_work": {"attempt_token": "private fencing token"},
        "roundtrip_marker": "kept",
    }}}}
    projected = task_memory_projection(value)
    checkpoint = projected["task"]["checkpoint"]
    state = checkpoint["state_data"]
    assert state["memory_audit"] == {"used_ids": ["memory-one"]}
    assert "memory_audit_history" not in state
    assert "_pending_fenced_work" not in state
    assert state["roundtrip_marker"] == "kept"
    assert checkpoint["state_data_omitted"] == ["_pending_fenced_work", "memory_audit_history"]
    assert task_memory_projection(projected)["task"]["checkpoint"] == checkpoint


def test_checkpoint_preflight_rejects_oversized_preserved_state():
    task = SimpleNamespace(to_dict=lambda: {"task_id": "task-one", "checkpoint": {
        "phase": "verification", "state_data": {"memory_context": _snapshot(), "marker": "x" * 4000},
    }})
    with pytest.raises(CheckpointResponseBudgetError):
        TaskStore._preflight_response_budget(task, 512)
    TaskStore._preflight_response_budget(task, 8192)


def test_memory_audit_truncation_survives_reprojection():
    value = {"task": {"checkpoint": {"state_data": {
        "memory_context": _snapshot(), "memory_audit": {"used_ids": [str(i) for i in range(9)]},
    }}}}
    projected = task_memory_projection(value)
    assert projected["task"]["checkpoint"]["state_data"]["memory_audit"]["truncated"] is True
    assert task_memory_projection(projected) == projected


def test_wire_projection_ignores_invalid_omission_metadata():
    value = {"task": {"checkpoint": {"state_data_omitted": [{}, None, "unknown"],
                                      "state_data": {"memory_context": _snapshot()}}}}
    assert "state_data_omitted" not in task_memory_projection(value)["task"]["checkpoint"]


def test_wire_projection_sanitizes_tasks_when_single_task_is_also_present():
    value = {"task": {"checkpoint": {"state_data": {"memory_context": _snapshot()}}},
             "tasks": [{"task_id": "other", "checkpoint": {"state_data": {
                 "_pending_fenced_work": {"attempt_token": "private-token"},
             }}}]}
    projected = task_memory_projection(value)
    assert "private-token" not in repr(projected)
    assert projected["tasks"][0]["checkpoint"]["state_data_omitted"] == ["_pending_fenced_work"]


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


def test_resume_refreshes_memory_before_agent_audit_then_keeps_gate(tmp_path):
    store = TaskStore(AgentStateStore(tmp_path / "state.sqlite3"))
    store._task_memory_context = lambda *_args, **_kwargs: _snapshot()
    task_id = "task-one"
    store.create(
        GoalContract(goal="resume with current memory"),
        ScopeContext(task_id=task_id),
        task_id=task_id,
    )
    store.transition(
        task_id,
        TaskStatus.ACTIVE,
        reason="start task",
        actor="test",
        idempotency_key="start-task",
    )

    resumed = store.resume(task_id, actor="test")

    assert resumed.status is TaskStatus.ACTIVE
    assert resumed.checkpoint.state_data["memory_context"] == _snapshot()
    assert resumed.checkpoint.state_data["memory_audit"]["used_ids"] == []
    assert resumed.checkpoint.state_data["memory_audit"]["not_used_reason"]
    next_checkpoint = store.checkpoint(
        task_id, TaskCheckpoint(phase="next"), actor="test"
    )
    assert next_checkpoint.checkpoint.phase == "next"
    audited = store.checkpoint(
        task_id,
        TaskCheckpoint(phase="next", state_data={"memory_audit": {"used_ids": ["memory-one"]}}),
        actor="test",
    )
    assert audited.checkpoint.state_data["memory_audit"] == {"used_ids": ["memory-one"]}


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
