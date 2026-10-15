from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from local_ai_hub import agent_tasks as agent_tasks_module
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope, ScopeContext
from local_ai_hub.agent_tasks import (
    CheckpointResponseBudgetError,
    GoalContract,
    TaskCheckpoint,
    TaskStatus,
    TaskStore,
)


def _contract() -> GoalContract:
    return GoalContract(goal="preflight task", acceptance_criteria=(), scope=AgentScope.TASK)


def _memory() -> dict[str, object]:
    return {
        "schema_version": 1,
        "tenant_key": "tenant-test",
        "instruction": "Use task memory carefully",
        "items": [{"id": "memory-1", "content": "grounded fact", "origin": "memory_store"}],
        "warnings": [],
        "estimated_tokens": 8,
    }


def _store(tmp_path) -> TaskStore:
    return TaskStore(AgentStateStore(tmp_path / "agent-state.sqlite3"))


def test_create_preflights_memory_before_task_persistence(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(store, "_task_memory_context", lambda *args, **kwargs: _memory())
    monkeypatch.setattr(agent_tasks_module, "task_memory_wire_tokens", lambda projected, requested: 129)
    commits = []
    monkeypatch.setattr(store, "_commit_create", lambda *args, **kwargs: commits.append(args))

    with pytest.raises(CheckpointResponseBudgetError):
        store.create(
            _contract(), ScopeContext(), task_id="create-budget", response_budget_tokens=128,
        )

    assert commits == []
    assert store.state_store.event_page("task:create-budget")["last_seq"] == 0


def test_create_persists_when_full_memory_response_fits(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(store, "_task_memory_context", lambda *args, **kwargs: _memory())
    monkeypatch.setattr(agent_tasks_module, "task_memory_wire_tokens", lambda projected, requested: 64)

    task = store.create(
        _contract(), ScopeContext(), task_id="create-budget-fit", response_budget_tokens=128,
    )

    assert task.checkpoint.state_data["memory_context"] == _memory()
    assert store.state_store.event_page(f"task:{task.task_id}")["last_seq"] == 1


def test_auto_worktree_create_preflights_before_git_mutation(tmp_path, monkeypatch):
    from local_ai_hub import process_utils

    store = _store(tmp_path)
    monkeypatch.setattr(store, "_task_memory_context", lambda *args, **kwargs: _memory())
    plan = SimpleNamespace(
        repo_root=str(tmp_path.resolve()),
        ttl_seconds=3600.0,
        expires_at=9999999999.0,
        response_metadata=lambda: {"success": True, "worktree_id": "worktree_000000000000"},
    )
    monkeypatch.setattr(process_utils, "prepare_git_worktree", lambda *args, **kwargs: plan)
    create_calls = []
    monkeypatch.setattr(process_utils, "create_git_worktree", lambda *args, **kwargs: create_calls.append(args))
    monkeypatch.setattr(agent_tasks_module, "task_memory_wire_tokens", lambda projected, requested: 129)
    commits = []
    monkeypatch.setattr(store, "_commit_create", lambda *args, **kwargs: commits.append(args))

    with pytest.raises(CheckpointResponseBudgetError):
        store.create(
            _contract(), ScopeContext(repository_id=str(tmp_path)), task_id="auto-create-budget",
            auto_worktree=True, response_budget_tokens=128,
        )

    assert create_calls == []
    assert commits == []


def test_auto_worktree_create_consumes_preflighted_plan_after_budget_fits(tmp_path, monkeypatch):
    from local_ai_hub import process_utils

    store = _store(tmp_path)
    monkeypatch.setattr(store, "_task_memory_context", lambda *args, **kwargs: _memory())
    plan = SimpleNamespace(
        repo_root=str(tmp_path.resolve()), ttl_seconds=3600.0, expires_at=9999999999.0,
        response_metadata=lambda: {"success": True, "worktree_id": "worktree_000000000000"},
    )
    monkeypatch.setattr(process_utils, "prepare_git_worktree", lambda *args, **kwargs: plan)
    create_calls = []

    def create(*args, **kwargs):
        create_calls.append((args, kwargs))
        return plan.response_metadata()

    monkeypatch.setattr(process_utils, "create_git_worktree", create)
    monkeypatch.setattr(agent_tasks_module, "task_memory_wire_tokens", lambda projected, requested: 64)

    task = store.create(
        _contract(), ScopeContext(repository_id=str(tmp_path)), task_id="auto-create-fit",
        auto_worktree=True, response_budget_tokens=128,
    )

    assert task.checkpoint.state_data["worktree"] == plan.response_metadata()
    assert len(create_calls) == 1
    assert create_calls[0][1]["prepared_plan"] is plan


def test_completion_returns_scheduled_worktree_cleanup_without_postcommit_write(tmp_path, monkeypatch):
    store = _store(tmp_path)
    created = store.create(_contract(), ScopeContext(), task_id="complete-scheduled-cleanup")
    state_data = {
        **created.checkpoint.state_data,
        "worktree": {
            "task_id": created.task_id,
            "owner": created.owner,
            "repo_root": str(tmp_path),
            "worktree_path": str(tmp_path / "worktree"),
            "worktree_id": "worktree-test",
            "branch": "hub/task-complete-scheduled-cleanup",
            "base_commit": "a" * 40,
            "created_at": 1.0,
            "ttl_seconds": 3600.0,
            "expires_at": 3601.0,
            "creator_pid": 1,
            "creator_creation_identity": 2,
            "creator_creation_identity_type": "test",
            "creator_executable": "python.exe",
        },
    }
    store.checkpoint(
        created.task_id,
        TaskCheckpoint(state_data=state_data),
        actor=created.owner,
        idempotency_key="worktree-checkpoint",
    )
    cleanup_calls = []
    monkeypatch.setattr(store, "cleanup_worktree", lambda *args, **kwargs: cleanup_calls.append(args))

    completed = store.complete(created.task_id, actor=created.owner)

    assert completed.status is TaskStatus.COMPLETED
    assert completed.checkpoint.state_data["worktree"]["cleanup_pending"] is True
    assert completed.checkpoint.state_data["worktree"]["cleanup_scheduled"] is True
    assert cleanup_calls == []


def test_idle_reaper_accepts_scheduled_worktree_before_expiry(tmp_path, monkeypatch):
    from local_ai_hub import process_utils, worktrees

    store = _store(tmp_path)
    created = store.create(
        _contract(), ScopeContext(repository_id=str(tmp_path)), task_id="scheduled-reaper",
    )
    worktree = {
        "task_id": created.task_id,
        "owner": created.owner,
        "repo_root": str(tmp_path),
        "worktree_path": str(tmp_path / "scheduled-worktree"),
        "worktree_id": "worktree-scheduled-reaper",
        "branch": "hub/task-scheduled-reaper",
        "base_commit": "a" * 40,
        "created_at": 1000.0,
        "ttl_seconds": 3600.0,
        "expires_at": 9999999999.0,
        "creator_pid": 1,
        "creator_creation_identity": 2,
        "creator_creation_identity_type": "test",
        "creator_executable": "python.exe",
    }
    store.checkpoint(
        created.task_id,
        TaskCheckpoint(state_data={**created.checkpoint.state_data, "worktree": worktree}),
        actor=created.owner,
        idempotency_key="scheduled-reaper-worktree",
    )
    completed = store.complete(created.task_id, actor=created.owner)
    monkeypatch.setattr(
        process_utils,
        "process_owner_state",
        lambda *args, **kwargs: pytest.fail("scheduled cleanup must not wait for creator exit"),
    )
    monkeypatch.setattr(worktrees, "is_hub_temporary_worktree", lambda path: True)
    monkeypatch.setattr(worktrees, "worktree_is_clean_ancestor", lambda *args, **kwargs: (True, ""))
    cleanup_calls = []
    monkeypatch.setattr(
        store,
        "cleanup_worktree",
        lambda *args, **kwargs: cleanup_calls.append((args, kwargs)) or {"success": True},
    )

    counts = store.cleanup_idle_worktrees()

    assert completed.status is TaskStatus.COMPLETED
    assert counts["cleaned"] == 1
    assert cleanup_calls


def test_prepared_worktree_plan_is_read_only_and_bound_to_create_request(tmp_path, monkeypatch):
    from subprocess import CompletedProcess

    from local_ai_hub import process_utils

    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    git_reads = []

    def read_git(args, **kwargs):
        git_reads.append((args, kwargs))
        return CompletedProcess(args, 0, "a" * 40 + "\n", "")

    monkeypatch.setattr(process_utils, "run_hidden", read_git)
    monkeypatch.setattr(process_utils.shutil, "which", lambda name: "git" if name == "git" else None)
    creator = {
        "pid": 123, "creation_identity": 456, "creation_identity_type": "test_identity",
        "executable": "C:/test/python.exe",
    }
    monkeypatch.setattr(process_utils, "process_identity", lambda pid: dict(creator))
    plan = process_utils.prepare_git_worktree(
        repo, branch_name="hub/task-prepared", task_id="prepared", owner="agent",
        created_at=1000.0, ttl_seconds=3600.0, expires_at=4600.0,
    )

    assert len(git_reads) == 1
    assert "worktree" not in " ".join(git_reads[0][0])
    rejected = process_utils.create_git_worktree(
        repo, branch_name="hub/task-prepared", task_id="prepared", owner="other-agent",
        created_at=1000.0, ttl_seconds=3600.0, expires_at=4600.0, prepared_plan=plan,
    )

    assert rejected["success"] is False
    assert len(git_reads) == 1


@pytest.mark.parametrize("action", ["create", "checkpoint", "fail", "transition", "complete"])
def test_sdk_task_coord_only_sends_budget_when_supplied(monkeypatch, action):
    from local_ai_hub.client import HubClient

    client = HubClient(auto_start=False)
    sent = []
    monkeypatch.setattr(client, "post", lambda path, payload, **kwargs: sent.append(dict(payload)) or {"success": True})

    client.coord(action=f"task_{action}", task_id="sdk-task")
    assert "response_budget_tokens" not in sent[-1]
    client.coord(action=f"task_{action}", task_id="sdk-task", response_budget_tokens=320)
    assert sent[-1]["response_budget_tokens"] == 320


def test_registered_task_mutation_wire_preflights_full_memory_and_preserves_error_flags(monkeypatch):
    from local_ai_hub import mcp_server
    from local_ai_hub.task_memory_wire import (
        normalize_task_memory_response,
        task_memory_projection,
        task_memory_wire_tokens,
    )

    memory_bundle = {
        **_memory(),
        "instruction": "grounded instruction " * 30,
        "items": [
            {"id": f"memory-{index}", "content": "evidence detail " * 45, "origin": "memory_store"}
            for index in range(2)
        ],
        "warnings": ["advisory " * 20],
        "estimated_tokens": 900,
    }
    task = {
        "task_id": "wire-task",
        "status": "planned",
        "owner": "agent",
        "lease_id": "",
        "created_at": 1.0,
        "updated_at": 1.0,
        "heartbeat_expires_at": 0.0,
        "context": {"repository_id": "C:/repo", "task_id": "wire-task"},
        "checkpoint": {
            "phase": "",
            "state_data": {
                "memory_context": memory_bundle,
                "memory_audit": {"used_ids": ["memory-1"], "source_checked": True},
            },
        },
    }
    success = {
        "success": True,
        "context_id": "context-wire",
        "request_id": "request-wire",
        "task": task,
    }
    projected = normalize_task_memory_response(task_memory_projection(success))
    adequate_budget = next(
        budget for budget in range(128, 4097)
        if task_memory_wire_tokens(projected, budget) <= budget
    )

    class RegisteredFakeClient:
        def __init__(self):
            self.requests = []

        def coord(self, **kwargs):
            self.requests.append(kwargs)
            budget = kwargs["response_budget_tokens"]
            required = task_memory_wire_tokens(projected, budget)
            if required > budget:
                return {
                    "success": False,
                    "context_id": "context-wire",
                    "request_id": "request-wire",
                    "error": "full task memory response exceeds the requested budget",
                    "terminal": True,
                    "retryable": False,
                    "mutation_applied": False,
                    "operation_not_started": True,
                }
            return success

    client = RegisteredFakeClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_: None)

    def invoke(budget):
        result = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
            "action": "task_create",
            "task": "wire task",
            "max_response_tokens": budget,
            "response_profile": "minimal",
        }))
        contents = result[0] if isinstance(result, tuple) else result
        return json.loads(next(item.text for item in contents if item.type == "text"))

    rejected = invoke(128)
    assert client.requests[-1]["response_budget_tokens"] == 128
    assert rejected["mutation_applied"] is False
    assert rejected["operation_not_started"] is True
    assert rejected["request_id"] == "request-wire"

    accepted = invoke(adequate_budget)
    assert client.requests[-1]["response_budget_tokens"] == adequate_budget
    assert accepted["context_id"] == "context-wire"
    assert accepted["request_id"] == "request-wire"
    assert accepted["task"]["checkpoint"]["state_data"]["memory_context"] == memory_bundle


@pytest.mark.parametrize("action", ["fail", "transition", "complete"])
def test_task_transition_preflights_before_event_or_state_write(tmp_path, monkeypatch, action):
    store = _store(tmp_path)
    created = store.create(_contract(), ScopeContext(), task_id=f"{action}-budget")
    current = replace(
        created,
        status=TaskStatus.ACTIVE,
        checkpoint=TaskCheckpoint(phase="existing", state_data={"memory_context": _memory()}),
    )
    monkeypatch.setattr(store, "get", lambda task_id: current)
    monkeypatch.setattr(store, "_validate_memory_audit", lambda _task: None)
    monkeypatch.setattr(agent_tasks_module, "task_memory_wire_tokens", lambda projected, requested: 129)
    commits = []
    monkeypatch.setattr(store, "_commit_update", lambda *args, **kwargs: commits.append(args))
    before_seq = store.state_store.event_page(f"task:{current.task_id}")["last_seq"]

    with pytest.raises(CheckpointResponseBudgetError):
        if action == "fail":
            store.fail(current.task_id, actor="agent", response_budget_tokens=128)
        elif action == "transition":
            store.transition(
                current.task_id, TaskStatus.WAITING, reason="pause", actor="agent",
                idempotency_key="transition-budget", response_budget_tokens=128,
            )
        else:
            store.complete(current.task_id, actor="agent", response_budget_tokens=128)

    assert commits == []
    assert store.state_store.event_page(f"task:{current.task_id}")["last_seq"] == before_seq

