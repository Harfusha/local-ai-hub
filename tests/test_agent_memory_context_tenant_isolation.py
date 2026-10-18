from __future__ import annotations

from pathlib import Path

import pytest

from local_ai_hub import trace_context
from local_ai_hub.agent_context import ContextCompiler, ContextRequest
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope, ScopeContext
from local_ai_hub.agent_incidents import IncidentStore
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStatus, MemoryStore
from local_ai_hub.agent_tasks import GoalContract, TaskStatus, TaskStore


def _record(
    *,
    scope: AgentScope,
    scope_id: str = "",
    root: Path | None = None,
    repository_id: str = "",
    key: str,
) -> MemoryRecord:
    provenance = {}
    if root is not None:
        provenance["root"] = str(root)
    if repository_id:
        provenance["repository_id"] = repository_id
    return MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=scope,
        scope_id=scope_id,
        key=key,
        value=key,
        status=MemoryStatus.CONFIRMED,
        source="user",
        provenance=provenance,
    )


def _ids(records: list[MemoryRecord]) -> set[str]:
    return {record.record_id for record in records}


def _seed_memory_projections(memory: MemoryStore, records) -> None:
    """Seed lookup projections directly; event publication is outside these tests."""
    for record in records:
        memory._save_record(record)


@pytest.mark.parametrize("seed_projections", [False, True])
def test_context_memory_uses_repository_task_and_global_scopes(tmp_path: Path, seed_projections):
    state = AgentStateStore(tmp_path / "agent_state.sqlite3")
    memory = MemoryStore(state)
    root = tmp_path / "repo"
    foreign_root = tmp_path / "other-repo"
    root.mkdir()
    foreign_root.mkdir()
    records = {
        "repo_current": _record(scope=AgentScope.REPOSITORY, scope_id=str(root), root=root, repository_id="repo-id", key="repo-current"),
        "repo_other_root": _record(scope=AgentScope.REPOSITORY, scope_id=str(foreign_root), root=foreign_root, repository_id="other-repo-id", key="repo-other-root"),
        "task_current": _record(scope=AgentScope.TASK, scope_id="task-current", root=root, key="task-current"),
        "task_other": _record(scope=AgentScope.TASK, scope_id="task-other", root=root, key="task-other"),
        "global_one": _record(scope=AgentScope.GLOBAL, key="global-one"),
        "global_two": _record(scope=AgentScope.GLOBAL, key="global-two"),
    }
    if seed_projections:
        _seed_memory_projections(memory, records.values())
    else:
        for record in records.values():
            memory.record(record, actor="user")

    found = memory.find_for_context(
        root=str(root), task_id="task-current", coordination_id="repo-id"
    )
    assert _ids(found) == {
        records["repo_current"].record_id,
        records["task_current"].record_id,
        records["global_one"].record_id,
        records["global_two"].record_id,
    }


def test_owner_global_memory_is_available_without_repository_context(tmp_path: Path):
    state = AgentStateStore(tmp_path / "agent_state.sqlite3")
    memory = MemoryStore(state)
    records = (
        _record(scope=AgentScope.GLOBAL, key="global-one"),
        _record(scope=AgentScope.GLOBAL, key="global-two"),
        _record(scope=AgentScope.REPOSITORY, scope_id="repo", root=Path("repo"), key="repo-only"),
    )
    for record in records:
        memory.record(record, actor="user")

    assert _ids(memory.find_for_context()) == {
        records[0].record_id,
        records[1].record_id,
    }


@pytest.mark.parametrize("seed_projections", [False, True])
def test_context_compiler_preserves_actual_repository_and_task_scope(tmp_path: Path, seed_projections):
    state = AgentStateStore(tmp_path / "agent_state.sqlite3")
    memory = MemoryStore(state)
    root = tmp_path / "repo"
    other_root = tmp_path / "other-repo"
    root.mkdir()
    other_root.mkdir()
    records = {
        "repo_current": _record(scope=AgentScope.REPOSITORY, scope_id=str(root), root=root, repository_id="repo-id", key="repo-current"),
        "repo_foreign": _record(scope=AgentScope.REPOSITORY, scope_id=str(other_root), root=other_root, repository_id="other-id", key="repo-foreign"),
        "task_current": _record(scope=AgentScope.TASK, scope_id="shared-task", root=root, key="task-current"),
        "task_other": _record(scope=AgentScope.TASK, scope_id="different-task", root=root, key="task-other"),
        "global": _record(scope=AgentScope.GLOBAL, key="global-owner-memory"),
    }
    if seed_projections:
        _seed_memory_projections(memory, records.values())
    else:
        for record in records.values():
            memory.record(record, actor="user")
    compiler = ContextCompiler(state, memory_store=memory)

    compiled = compiler.compile(ContextRequest(
        task_id="shared-task", root=str(root), coordination_id="repo-id"
    ))
    memory_ids = {
        element.element_id
        for element in compiled.elements
        if element.source_kind == "memory_record"
    }
    assert memory_ids == {
        records["repo_current"].record_id,
        records["task_current"].record_id,
        records["global"].record_id,
    }


@pytest.mark.parametrize("seed_projections", [False, True])
def test_task_create_and_resume_keep_repository_and_global_memory(tmp_path: Path, seed_projections):
    state = AgentStateStore(tmp_path / "agent_state.sqlite3")
    tasks = TaskStore(state)
    memory = MemoryStore(state)
    incidents = IncidentStore(state)
    tasks.set_memory_adoption(
        memory_store=memory,
        context_compiler=ContextCompiler(state, task_store=tasks, memory_store=memory),
        incident_store=incidents,
    )
    root = tmp_path / "repo"
    foreign_root = tmp_path / "other-repo"
    root.mkdir()
    foreign_root.mkdir()
    from local_ai_hub.project_config import resolve_project_context

    coordination_id = resolve_project_context(root, state.db_path.parent).coordination_id
    records = {
        "repo_current": _record(scope=AgentScope.REPOSITORY, scope_id=str(root), root=root, repository_id=coordination_id, key="repo-current"),
        "repo_foreign": _record(scope=AgentScope.REPOSITORY, scope_id=str(foreign_root), root=foreign_root, repository_id="other-repo", key="repo-foreign"),
        "global_one": _record(scope=AgentScope.GLOBAL, key="global-one"),
        "global_two": _record(scope=AgentScope.GLOBAL, key="global-two"),
    }
    if seed_projections:
        _seed_memory_projections(memory, records.values())
    else:
        for record in records.values():
            memory.record(record, actor="user")
    expected = {
        records["repo_current"].record_id,
        records["global_one"].record_id,
        records["global_two"].record_id,
    }

    task = tasks.create(
        GoalContract(goal="Use current repository and owner-global facts"),
        ScopeContext(branch="main", task_id="memory-task"),
        task_id="memory-task",
        repo_root=str(root),
    )
    created_ids = {item["id"] for item in task.checkpoint.state_data["memory_context"]["items"]}
    tasks.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="test", idempotency_key="scope-start")
    tasks.transition(task.task_id, TaskStatus.BLOCKED, reason="wait", actor="test", idempotency_key="scope-block")
    resumed = tasks.resume(task.task_id, actor="test", idempotency_key="scope-resume")

    resumed_ids = {item["id"] for item in resumed.checkpoint.state_data["memory_context"]["items"]}
    assert created_ids == expected
    assert resumed_ids == expected
    assert records["repo_foreign"].record_id not in repr(task.checkpoint.state_data)
    assert records["repo_foreign"].record_id not in repr(resumed.checkpoint.state_data)


def test_context_request_rejects_retired_tenant_argument():
    with pytest.raises(TypeError):
        ContextRequest(task_id="task", tenant="retired-label")
