from __future__ import annotations

from pathlib import Path

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
    tenant: str = "",
    key: str,
) -> MemoryRecord:
    provenance = {}
    if root is not None:
        provenance["root"] = str(root)
    if tenant:
        provenance["tenant"] = tenant
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


def test_find_for_context_filters_explicit_foreign_tenant_for_repository_and_global(tmp_path: Path):
    state = AgentStateStore(tmp_path / "agent_state.sqlite3")
    memory = MemoryStore(state)
    root = tmp_path / "repo"
    root.mkdir()
    records = {
        "repo_current": _record(scope=AgentScope.REPOSITORY, scope_id=str(root), root=root, tenant="tenant-a", key="repo-current"),
        "repo_foreign": _record(scope=AgentScope.REPOSITORY, scope_id=str(root), root=root, tenant="tenant-b", key="repo-foreign"),
        "repo_tenantless": _record(scope=AgentScope.REPOSITORY, scope_id=str(root), root=root, key="repo-tenantless"),
        "task_current": _record(scope=AgentScope.TASK, scope_id="shared-task", root=root, tenant="tenant-a", key="task-current"),
        "task_foreign": _record(scope=AgentScope.TASK, scope_id="shared-task", root=root, tenant="tenant-b", key="task-foreign"),
        "global_current": _record(scope=AgentScope.GLOBAL, tenant="tenant-a", key="global-current"),
        "global_foreign": _record(scope=AgentScope.GLOBAL, tenant="tenant-b", key="global-foreign"),
        "global_tenantless": _record(scope=AgentScope.GLOBAL, key="global-tenantless"),
    }
    for record in records.values():
        memory.record(record, actor="user")

    found = memory.find_for_context(root=str(root), task_id="shared-task", tenant="tenant-a")

    assert _ids(found) == {
        records["repo_current"].record_id,
        records["task_current"].record_id,
        records["global_current"].record_id,
        records["global_tenantless"].record_id,
    }


def test_find_for_context_without_tenant_returns_only_tenantless_global(tmp_path: Path):
    state = AgentStateStore(tmp_path / "agent_state.sqlite3")
    memory = MemoryStore(state)
    root = tmp_path / "repo"
    root.mkdir()
    records = {
        "repo_tenantless": _record(scope=AgentScope.REPOSITORY, scope_id=str(root), root=root, key="repo-tenantless"),
        "repo_owned": _record(scope=AgentScope.REPOSITORY, scope_id=str(root), root=root, tenant="tenant-a", key="repo-owned"),
        "task_tenantless": _record(scope=AgentScope.TASK, scope_id="shared-task", root=root, key="task-tenantless"),
        "global_tenantless": _record(scope=AgentScope.GLOBAL, key="global-tenantless"),
        "global_owned": _record(scope=AgentScope.GLOBAL, tenant="tenant-a", key="global-owned"),
    }
    _seed_memory_projections(memory, records.values())

    assert _ids(memory.find_for_context(root=str(root), task_id="shared-task")) == {
        records["global_tenantless"].record_id,
    }


def test_context_compiler_filters_foreign_tenant_before_returning_memory(tmp_path: Path):
    state = AgentStateStore(tmp_path / "agent_state.sqlite3")
    memory = MemoryStore(state)
    root = tmp_path / "repo"
    root.mkdir()
    records = {
        "repo_current": _record(scope=AgentScope.REPOSITORY, scope_id=str(root), root=root, tenant="tenant-a", key="repo-current"),
        "repo_foreign": _record(scope=AgentScope.REPOSITORY, scope_id=str(root), root=root, tenant="tenant-b", key="repo-foreign"),
        "task_current": _record(scope=AgentScope.TASK, scope_id="shared-task", root=root, tenant="tenant-a", key="task-current"),
        "task_foreign": _record(scope=AgentScope.TASK, scope_id="shared-task", root=root, tenant="tenant-b", key="task-foreign"),
        "global_current": _record(scope=AgentScope.GLOBAL, tenant="tenant-a", key="global-current"),
        "global_foreign": _record(scope=AgentScope.GLOBAL, tenant="tenant-b", key="global-foreign"),
        "global_tenantless": _record(scope=AgentScope.GLOBAL, key="global-tenantless"),
    }
    for record in records.values():
        memory.record(record, actor="user")
    compiler = ContextCompiler(state, memory_store=memory)

    compiled = compiler.compile(
        ContextRequest(task_id="shared-task", root=str(root), tenant="tenant-a")
    )

    memory_ids = {
        element.element_id
        for element in compiled.elements
        if element.source_kind == "memory_record"
    }
    assert memory_ids == {
        records["repo_current"].record_id,
        records["task_current"].record_id,
        records["global_current"].record_id,
        records["global_tenantless"].record_id,
    }

    unscoped_compiled = compiler.compile(
        ContextRequest(task_id="shared-task", root=str(root), tenant="")
    )
    unscoped_memory_ids = {
        element.element_id
        for element in unscoped_compiled.elements
        if element.source_kind == "memory_record"
    }
    assert unscoped_memory_ids == {records["global_tenantless"].record_id}


def test_task_create_and_resume_exclude_same_root_foreign_tenant_memory(tmp_path: Path):
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
    root.mkdir()
    records = {
        "repo_current": _record(scope=AgentScope.REPOSITORY, scope_id=str(root), root=root, tenant="tenant-a", key="repo-current"),
        "repo_foreign": _record(scope=AgentScope.REPOSITORY, scope_id=str(root), root=root, tenant="tenant-b", key="repo-foreign"),
        "global_current": _record(scope=AgentScope.GLOBAL, tenant="tenant-a", key="global-current"),
        "global_foreign": _record(scope=AgentScope.GLOBAL, tenant="tenant-b", key="global-foreign"),
        "global_tenantless": _record(scope=AgentScope.GLOBAL, key="global-tenantless"),
    }
    for record in records.values():
        memory.record(record, actor="user")
    expected = {
        records["repo_current"].record_id,
        records["global_current"].record_id,
        records["global_tenantless"].record_id,
    }

    token = trace_context.set_context(tenant="tenant-a")
    try:
        task = tasks.create(
            GoalContract(goal="scoped task"),
            ScopeContext(branch="main", task_id="memory-task"),
            task_id="memory-task",
            repo_root=str(root),
        )
        created_ids = {item["id"] for item in task.checkpoint.state_data["memory_context"]["items"]}
        tasks.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="test", idempotency_key="tenant-start")
        tasks.transition(task.task_id, TaskStatus.BLOCKED, reason="wait", actor="test", idempotency_key="tenant-block")
        resumed = tasks.resume(task.task_id, actor="test", idempotency_key="tenant-resume")
    finally:
        trace_context.reset_context(token)

    resumed_ids = {item["id"] for item in resumed.checkpoint.state_data["memory_context"]["items"]}
    assert created_ids == expected
    assert resumed_ids == expected
