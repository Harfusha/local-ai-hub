from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from local_ai_hub import trace_context
from local_ai_hub.agent_context import ContextCompiler
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope, ScopeContext
from local_ai_hub.agent_incidents import IncidentStore
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStatus, MemoryStore
from local_ai_hub.agent_tasks import GoalContract, TaskStatus, TaskStore


def test_task_memory_snapshot_preserves_freshness_provenance_and_evidence(tmp_path: Path):
    state = AgentStateStore(tmp_path / "agent_state.sqlite3")
    tasks = TaskStore(state)
    memory = MemoryStore(state)
    root = tmp_path / "repo"
    root.mkdir()
    record = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.REPOSITORY,
        scope_id=str(root),
        key="verified-finding",
        value="keep the scoped lookup",
        status=MemoryStatus.CONFIRMED,
        source="user",
        evidence_ids=("ev-current-1",),
        repository_revision="rev-1",
        path_refs=("src/example.py",),
        provenance={"root": str(root), "tenant": "tenant-a"},
    )
    memory._save_record(record)
    compiler = ContextCompiler(state, task_store=tasks, memory_store=memory)
    tasks.set_memory_adoption(memory_store=memory, context_compiler=compiler, incident_store=IncidentStore(state))

    token = trace_context.set_context(tenant="tenant-a")
    try:
        task = tasks.create(
            GoalContract(goal="use scoped memory"),
            ScopeContext(task_id="memory-task"),
            task_id="memory-task",
            repo_root=str(root),
        )
    finally:
        trace_context.reset_context(token)

    snapshot = task.checkpoint.state_data["memory_context"]
    assert snapshot["status"] == "compiled"
    assert snapshot["context_stale"] is False
    assert snapshot["scope"]["tenant_bound"] is True
    assert snapshot["used_memory_ids"] == [record.record_id]
    assert snapshot["evidence_ids"] == ["ev-current-1"]
    item = snapshot["items"][0]
    assert item["freshness"] == record.updated_at
    assert item["provenance"]["repository_revision"] == "rev-1"
    assert item["provenance"]["evidence_ids"] == ["ev-current-1"]


def test_task_memory_fallback_is_bounded_and_does_not_echo_error_or_tenant(tmp_path: Path):
    class UnavailableCompiler:
        def compile(self, _request):
            raise RuntimeError("tenant-a api_key=should-not-escape")

    state = AgentStateStore(tmp_path / "agent_state.sqlite3")
    tasks = TaskStore(state)
    memory = MemoryStore(state)
    tasks.set_memory_adoption(memory_store=memory, context_compiler=UnavailableCompiler())

    token = trace_context.set_context(tenant="tenant-a")
    try:
        task = tasks.create(
            GoalContract(goal="continue without unavailable memory"),
            ScopeContext(task_id="fallback-task"),
            task_id="fallback-task",
            repo_root=str(tmp_path / "repo"),
        )
    finally:
        trace_context.reset_context(token)

    snapshot = task.checkpoint.state_data["memory_context"]
    assert snapshot == {
        "status": "unavailable",
        "items": [],
        "used_memory_ids": [],
        "evidence_ids": [],
    }
    assert "tenant-a" not in str(snapshot)
    assert "api_key" not in str(snapshot)


def test_task_resume_recompiles_context_after_memory_becomes_stale(tmp_path: Path):
    state = AgentStateStore(tmp_path / "agent_state.sqlite3")
    tasks = TaskStore(state)
    memory = MemoryStore(state)
    root = tmp_path / "repo"
    root.mkdir()
    record = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.REPOSITORY,
        scope_id=str(root),
        key="temporary-fact",
        value="valid before recheck",
        status=MemoryStatus.CONFIRMED,
        source="user",
        provenance={"root": str(root), "tenant": "tenant-a"},
    )
    memory._save_record(record)
    compiler = ContextCompiler(state, task_store=tasks, memory_store=memory)
    tasks.set_memory_adoption(memory_store=memory, context_compiler=compiler)

    token = trace_context.set_context(tenant="tenant-a")
    try:
        task = tasks.create(
            GoalContract(goal="recheck memory on resume"),
            ScopeContext(task_id="stale-task"),
            task_id="stale-task",
            repo_root=str(root),
        )
        assert task.checkpoint.state_data["memory_context"]["used_memory_ids"] == [record.record_id]
        memory._save_record(replace(record, status=MemoryStatus.STALE))
        tasks.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="test", idempotency_key="stale-start")
        tasks.transition(task.task_id, TaskStatus.BLOCKED, reason="wait", actor="test", idempotency_key="stale-block")
        resumed = tasks.resume(task.task_id, actor="test", idempotency_key="stale-resume")
    finally:
        trace_context.reset_context(token)

    snapshot = resumed.checkpoint.state_data["memory_context"]
    assert snapshot["used_memory_ids"] == []


def test_task_creation_shares_repository_memory_across_worktrees_and_isolates_identity(tmp_path: Path):
    state = AgentStateStore(tmp_path / "agent_state.sqlite3")
    tasks = TaskStore(state)
    memory = MemoryStore(state)
    root = tmp_path / "repo"
    root.mkdir()
    records = {
        "repo": MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.REPOSITORY,
            scope_id=str(root),
            key="repository-guidance",
            value="shared across worktrees",
            status=MemoryStatus.CONFIRMED,
            source="user",
            provenance={"root": str(root), "tenant": "tenant-a"},
        ),
        "worktree_a": MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.WORKTREE,
            scope_id="worktree-a",
            key="local-guidance-a",
            value="only worktree a",
            status=MemoryStatus.CONFIRMED,
            source="user",
            provenance={"root": str(root), "tenant": "tenant-a"},
        ),
        "worktree_b": MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.WORKTREE,
            scope_id="worktree-b",
            key="local-guidance-b",
            value="only worktree b",
            status=MemoryStatus.CONFIRMED,
            source="user",
            provenance={"root": str(root), "tenant": "tenant-a"},
        ),
        "foreign_tenant": MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            scope_id=str(root),
            key="foreign-guidance",
            value="must not cross tenants",
            status=MemoryStatus.CONFIRMED,
            source="user",
            provenance={"root": str(root), "tenant": "tenant-b"},
        ),
    }
    for record in records.values():
        memory._save_record(record)
    compiler = ContextCompiler(state, task_store=tasks, memory_store=memory)
    tasks.set_memory_adoption(memory_store=memory, context_compiler=compiler)

    token = trace_context.set_context(tenant="tenant-a")
    try:
        task_a = tasks.create(
            GoalContract(goal="inspect worktree a"),
            ScopeContext(repository_id=str(root), clone_id="clone-a", worktree_id="worktree-a", task_id="task-a"),
            task_id="task-a",
            repo_root=str(root),
        )
        task_b = tasks.create(
            GoalContract(goal="inspect worktree b"),
            ScopeContext(repository_id=str(root), clone_id="clone-b", worktree_id="worktree-b", task_id="task-b"),
            task_id="task-b",
            repo_root=str(root),
        )
    finally:
        trace_context.reset_context(token)

    snapshot_a = task_a.checkpoint.state_data["memory_context"]
    snapshot_b = task_b.checkpoint.state_data["memory_context"]
    assert set(snapshot_a["used_memory_ids"]) == {records["repo"].record_id, records["worktree_a"].record_id}
    assert set(snapshot_b["used_memory_ids"]) == {records["repo"].record_id, records["worktree_b"].record_id}
    assert records["foreign_tenant"].record_id not in set(snapshot_a["used_memory_ids"] + snapshot_b["used_memory_ids"])
    assert snapshot_a["scope"]["tenant_bound"] and snapshot_b["scope"]["tenant_bound"]
    assert snapshot_a["scope"]["worktree_bound"] and snapshot_b["scope"]["worktree_bound"]
