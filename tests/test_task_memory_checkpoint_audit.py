from __future__ import annotations

from dataclasses import asdict
from types import SimpleNamespace

import pytest

from local_ai_hub import trace_context
from local_ai_hub.agent_context import ContextCompiler
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope, ScopeContext
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStatus, MemoryStore
from local_ai_hub.agent_tasks import CompletionGateError, GoalContract, TaskCheckpoint, TaskStore
from task_memory_support import repository_memory_id


@pytest.fixture
def make_task(tmp_path):
    token = trace_context.set_context(tenant="tenant-a")
    count = 0

    def make(*, volatile=False, with_memory=True):
        nonlocal count
        count += 1
        root = tmp_path / f"repo-{count}"
        root.mkdir()
        state = AgentStateStore(tmp_path / f"state-{count}.sqlite3")
        tasks = TaskStore(state)
        memory = MemoryStore(state)
        repository_id = repository_memory_id(root, state)
        record = None
        if with_memory:
            record = memory.record(MemoryRecord.create(
                kind=MemoryKind.FACT, scope=AgentScope.REPOSITORY, scope_id=repository_id,
                key="parser identifiers", value="Parser identifier tokenization uses Unicode rules",
                source="user", status=MemoryStatus.CONFIRMED, confidence=1.0,
                provenance={"root": str(root), "repository_id": repository_id, "tenant": "tenant-a", "volatile": volatile},
            ), actor="user")
        tasks.set_memory_adoption(memory_store=memory, context_compiler=ContextCompiler(state, task_store=tasks, memory_store=memory))
        task_id = f"checkpoint-memory-{count}"
        task = tasks.create(
            GoalContract(goal="Fix parser identifier tokenization"),
            ScopeContext(repository_id=str(root), task_id=task_id),
            task_id=task_id, repo_root=str(root),
        )
        return tasks, memory, root, task, record

    try:
        yield make
    finally:
        trace_context.reset_context(token)


def test_next_checkpoint_requires_declaration_without_mutating_task_or_events(make_task):
    tasks, _, _, task, _ = make_task()
    before = tasks.state_store.events(f"task:{task.task_id}")
    with pytest.raises(CompletionGateError, match="requires checkpoint memory_audit"):
        tasks.checkpoint(task.task_id, TaskCheckpoint(phase="edit"))
    after = tasks.get(task.task_id)
    assert after.checkpoint == task.checkpoint
    assert after.owner == task.owner
    assert asdict(after.context) == asdict(task.context)
    assert tasks.state_store.events(f"task:{task.task_id}") == before


@pytest.mark.parametrize("use_memory", [True, False])
def test_known_usage_or_reason_is_accepted_and_carries_forward(make_task, use_memory):
    tasks, _, _, task, record = make_task()
    audit = {"used_ids": [record.record_id]} if use_memory else {"used_ids": [], "not_used_reason": "Current source made this advisory fact unnecessary"}
    before_events = len(tasks.state_store.events(f"task:{task.task_id}"))
    updated = tasks.checkpoint(task.task_id, TaskCheckpoint(phase="edit", state_data={"memory_audit": audit}))
    assert updated.checkpoint.state_data["memory_context"] == task.checkpoint.state_data["memory_context"]
    assert updated.checkpoint.state_data["memory_audit"] == audit
    assert len(tasks.state_store.events(f"task:{task.task_id}")) == before_events + 1
    carried = tasks.checkpoint(task.task_id, TaskCheckpoint(phase="verify"))
    assert carried.checkpoint.state_data["memory_audit"] == audit
    assert carried.owner == task.owner
    assert asdict(carried.context) == asdict(task.context)
    assert len(tasks.state_store.events(f"task:{task.task_id}")) == before_events + 2


def test_unknown_memory_id_is_rejected_at_checkpoint(make_task):
    tasks, _, _, task, _ = make_task()
    with pytest.raises(CompletionGateError, match="unavailable memory IDs"):
        tasks.checkpoint(task.task_id, TaskCheckpoint(state_data={"memory_audit": {"used_ids": ["foreign-or-unknown"]}}))
    assert tasks.get(task.task_id).checkpoint == task.checkpoint


def test_no_memory_ordinary_checkpoint_is_unchanged(make_task):
    tasks, _, _, task, _ = make_task(with_memory=False)
    assert "memory_context" not in task.checkpoint.state_data
    updated = tasks.checkpoint(task.task_id, TaskCheckpoint(phase="edit", next_action="inspect current source"))
    assert updated.checkpoint.phase == "edit"
    assert updated.checkpoint.next_action == "inspect current source"
    assert "memory_audit" not in updated.checkpoint.state_data


def test_resume_requires_fresh_next_checkpoint_declaration(make_task):
    tasks, _, _, task, record = make_task()
    tasks.checkpoint(task.task_id, TaskCheckpoint(state_data={"memory_audit": {"used_ids": [record.record_id]}}))
    resumed = tasks.resume(task.task_id, actor="user", idempotency_key="fresh-memory-attempt")
    assert resumed.checkpoint.state_data["memory_audit"] is None
    with pytest.raises(CompletionGateError, match="requires checkpoint memory_audit"):
        tasks.checkpoint(task.task_id, TaskCheckpoint(phase="edit"))
    updated = tasks.checkpoint(task.task_id, TaskCheckpoint(state_data={"memory_audit": {"used_ids": [], "not_used_reason": "Rechecked this attempt against current source"}}))
    assert updated.checkpoint.state_data["memory_audit"]["not_used_reason"]


def test_volatile_usage_requires_same_source_check_policy_as_completion(make_task):
    tasks, _, _, task, record = make_task(volatile=True)
    with pytest.raises(CompletionGateError, match=r"lacks (?:a )?current-source check"):
        tasks.checkpoint(task.task_id, TaskCheckpoint(state_data={"memory_audit": {"used_ids": [record.record_id]}}))
    audit = {"used_ids": [record.record_id], "source_checks": {record.record_id: {"source": "current repository source inspection"}}}
    updated = tasks.checkpoint(task.task_id, TaskCheckpoint(state_data={"memory_audit": audit}))
    assert updated.checkpoint.state_data["memory_audit"] == audit


def test_healthy_empty_resume_has_no_irrelevant_memory_audit_friction(make_task):
    tasks, memory, root, task, record = make_task()
    assert memory.delete(record.record_id, scope=AgentScope.REPOSITORY, scope_id=repository_memory_id(root, memory.state_store), repository_id=repository_memory_id(root, memory.state_store), root=str(root), tenant="tenant-a")
    resumed = tasks.resume(task.task_id, actor="user", idempotency_key="empty-memory-attempt")
    bundle = resumed.checkpoint.state_data.get("memory_context")
    assert bundle is None or (bundle["items"] == [] and bundle["warnings"] == [] and not bundle["instruction"])
    updated = tasks.checkpoint(task.task_id, TaskCheckpoint(phase="edit"))
    assert updated.checkpoint.phase == "edit"


@pytest.mark.parametrize("warning", ["memory_context_unavailable", "memory_expired_skipped"])
def test_warning_only_checkpoint_requires_documented_reason(make_task, warning):
    tasks, memory, _, task, _ = make_task()

    class Compiler:
        def compile(self, request):
            if warning == "memory_context_unavailable":
                raise RuntimeError("backend unavailable")
            return SimpleNamespace(elements=(), warnings=({"code": warning},))

    tasks.set_memory_adoption(memory_store=memory, context_compiler=Compiler())
    resumed = tasks.resume(task.task_id, actor="user", idempotency_key="warning-memory-attempt")
    assert resumed.checkpoint.state_data["memory_context"]["items"] == []
    with pytest.raises(CompletionGateError, match="requires checkpoint memory_audit"):
        tasks.checkpoint(task.task_id, TaskCheckpoint(phase="edit"))
    updated = tasks.checkpoint(task.task_id, TaskCheckpoint(state_data={"memory_audit": {"used_ids": [], "not_used_reason": "No usable advisory memory was available"}}))
    assert updated.checkpoint.state_data["memory_audit"]["not_used_reason"]
