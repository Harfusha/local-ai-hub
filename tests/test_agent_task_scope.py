from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from local_ai_hub import trace_context
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope, ScopeContext
from local_ai_hub.agent_tasks import (
    GoalContract,
    TaskCheckpoint,
    TaskState,
    TaskStatus,
    TaskStore,
    _task_scope_values,
)


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    return TaskStore(AgentStateStore(tmp_path / "agent_state.sqlite3"))


def _create_task(store: TaskStore, root: Path | None, tenant: str, task_id: str) -> TaskState:
    token = trace_context.set_context(tenant=tenant)
    try:
        task = store.create(
            GoalContract(goal="scoped task", acceptance_criteria=("receipt",), scope=AgentScope.TASK),
            ScopeContext(repository_id="not-a-path", task_id=task_id),
            task_id=task_id,
            repo_root=str(root) if root is not None else "",
        )
    finally:
        trace_context.reset_context(token)
    return store.transition(
        task.task_id,
        TaskStatus.ACTIVE,
        reason="start",
        actor="agent",
        idempotency_key=f"start-{task_id}",
    )


def test_reaper_filters_root_and_tenant_and_auto_recovers_only_match(store: TaskStore, tmp_path: Path):
    root_a = tmp_path / "repo-a"
    root_b = tmp_path / "repo-b"
    root_a.mkdir()
    root_b.mkdir()
    matching = _create_task(store, root_a, "tenant-a", "matching")
    wrong_root = _create_task(store, root_b, "tenant-a", "wrong-root")
    wrong_tenant = _create_task(store, root_a, "tenant-b", "wrong-tenant")
    now = max(task.heartbeat_expires_at for task in (matching, wrong_root, wrong_tenant)) + 10

    reaped = store.recover_zombie_tasks(
        now=now,
        repo_root=root_a,
        tenant="tenant-a",
    )

    assert reaped == ["matching"]
    assert store.get("matching").status is TaskStatus.WAITING
    assert store.get("wrong-root").status is TaskStatus.ACTIVE
    assert store.get("wrong-tenant").status is TaskStatus.ACTIVE


def test_reaper_task_id_filter_is_narrow(store: TaskStore, tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    selected = _create_task(store, root, "tenant-a", "selected")
    other = _create_task(store, root, "tenant-a", "other")
    now = max(selected.heartbeat_expires_at, other.heartbeat_expires_at) + 10

    reaped = store.reap_expired_heartbeats(
        now=now,
        repo_root=root,
        tenant="tenant-a",
        task_id="selected",
    )

    assert reaped == ["selected"]
    assert store.get("selected").status is TaskStatus.ABANDONED
    assert store.get("other").status is TaskStatus.ACTIVE


def test_reaper_revalidates_scope_and_status_before_transition(store: TaskStore, tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    task = _create_task(store, root, "tenant-a", "raced")
    now = task.heartbeat_expires_at + 10
    original_transition = store.transition

    def change_status_before_reap(task_id, target, **kwargs):
        if kwargs.get("actor") == "system":
            original_transition(
                task_id,
                TaskStatus.WAITING,
                reason="concurrent owner update",
                actor="owner",
                idempotency_key="concurrent-owner-update",
            )
        return original_transition(task_id, target, **kwargs)

    monkeypatch.setattr(store, "transition", change_status_before_reap)

    reaped = store.reap_expired_heartbeats(now=now, repo_root=root, tenant="tenant-a")

    assert reaped == []
    assert store.get("raced").status is TaskStatus.WAITING


def test_reaper_fails_closed_without_task_provenance(store: TaskStore, tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    task = _create_task(store, None, "tenant-a", "unscoped")
    assert store.reap_expired_heartbeats(now=task.heartbeat_expires_at + 10) == []
    reaped = store.reap_expired_heartbeats(
        now=task.heartbeat_expires_at + 10,
        repo_root=root,
        tenant="tenant-a",
    )
    assert reaped == []
    assert store.get("unscoped").status is TaskStatus.ACTIVE


def test_malformed_scope_provenance_is_excluded(store: TaskStore, tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    task = _create_task(store, root, "tenant-a", "malformed")
    state_data = dict(task.checkpoint.state_data)
    state_data["_agent_task_scope"] = {"version": 2, "repo_root": str(root), "tenant_key": "a" * 64}
    malformed = replace(task, checkpoint=replace(task.checkpoint, state_data=state_data))
    assert _task_scope_values(malformed) == ("", "")


def test_checkpoint_cannot_replace_server_scope(store: TaskStore, tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    task = _create_task(store, root, "tenant-a", "immutable-scope")
    changed_scope = dict(task.checkpoint.state_data["_agent_task_scope"])
    changed_scope["repo_root"] = str(tmp_path)
    with pytest.raises(ValueError, match="_agent_task_scope is server-managed"):
        store.checkpoint(
            task.task_id,
            TaskCheckpoint(state_data={"_agent_task_scope": changed_scope}),
            actor="agent",
            idempotency_key="scope-tamper",
        )


def test_dataset_exports_only_scoped_tasks_and_optional_task_id(store: TaskStore, tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    other_root = tmp_path / "other"
    root.mkdir()
    other_root.mkdir()
    matching = _create_task(store, root, "tenant-a", "match-1")
    same_scope = _create_task(store, root, "tenant-a", "match-2")
    wrong_root = _create_task(store, other_root, "tenant-a", "wrong-root")
    wrong_tenant = _create_task(store, root, "tenant-b", "wrong-tenant")
    completed = [
        replace(task, status=TaskStatus.COMPLETED, verification_receipts={"receipt": {}})
        for task in (matching, same_scope, wrong_root, wrong_tenant)
    ]
    monkeypatch.setattr(store, "list_tasks", lambda **kwargs: completed)
    output = root / "exports" / "dataset.jsonl"

    result = store.curate_training_dataset(
        "exports/dataset.jsonl",
        repo_root=root,
        tenant="tenant-a",
        task_id="match-2",
    )

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert result["count"] == 1
    assert [row["task_id"] for row in rows] == ["match-2"]


def test_dataset_rejects_traversal_and_symlink_escape(store: TaskStore, tmp_path: Path):
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    with pytest.raises(ValueError, match="repo_root"):
        store.curate_training_dataset(str(root / "dataset.jsonl"))
    with pytest.raises(ValueError, match="inside repo_root"):
        store.curate_training_dataset("../outside.jsonl", repo_root=root, tenant="tenant-a")

    link = root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable")
    with pytest.raises(ValueError, match="inside repo_root"):
        store.curate_training_dataset("escape/dataset.jsonl", repo_root=root, tenant="tenant-a")


def test_dataset_enforces_serialized_byte_budget(store: TaskStore, tmp_path: Path, monkeypatch):
    import local_ai_hub.agent_tasks as agent_tasks_module

    root = tmp_path / "repo"
    root.mkdir()
    task = _create_task(store, root, "tenant-a", "large-sample")
    completed = replace(
        task,
        status=TaskStatus.COMPLETED,
        contract=replace(task.contract, goal="large" * 100),
        verification_receipts={"receipt": {}},
    )
    monkeypatch.setattr(store, "list_tasks", lambda **kwargs: [completed])
    monkeypatch.setattr(agent_tasks_module, "MAX_TRAINING_DATASET_BYTES", 64)
    output = root / "dataset.jsonl"

    with pytest.raises(ValueError, match="byte limit"):
        store.curate_training_dataset(
            "dataset.jsonl", repo_root=root, tenant="tenant-a"
        )

    assert not output.exists()
