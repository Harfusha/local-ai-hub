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
    CompletionGateError,
    GoalContract,
    TaskCheckpoint,
    TaskStatus,
    TaskStore,
    TaskWorktreeError,
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


def _mock_auto_worktree(monkeypatch, tmp_path):
    from local_ai_hub import process_utils

    def prepare(root, *, branch_name, task_id, owner, created_at, ttl_seconds, expires_at, **kwargs):
        metadata = {
            "success": True,
            "lease_id": "lease_000000000001",
            "worktree_id": "worktree_000000000001",
            "worktree_path": str(tmp_path / "scheduled-worktree"),
            "branch": branch_name,
            "base_commit": "a" * 40,
            "repo_root": str(tmp_path.resolve()),
            "task_id": task_id,
            "owner": owner,
            "created_at": created_at,
            "ttl_seconds": ttl_seconds,
            "expires_at": expires_at,
            "creator_pid": 1,
            "creator_creation_identity": 2,
            "creator_creation_identity_type": "test",
            "creator_executable": "python.exe",
        }
        return SimpleNamespace(
            repo_root=str(tmp_path.resolve()), ttl_seconds=ttl_seconds, expires_at=expires_at,
            response_metadata=lambda: metadata,
        )

    monkeypatch.setattr(process_utils, "prepare_git_worktree", prepare)
    monkeypatch.setattr(
        process_utils, "create_git_worktree", lambda *args, prepared_plan, **kwargs: prepared_plan.response_metadata(),
    )


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


def test_malformed_memory_audit_still_rejects_checkpoint_before_persistence(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(store, "_task_memory_context", lambda *args, **kwargs: _memory())
    task = store.create(_contract(), ScopeContext(), task_id="invalid-memory-audit")
    invalid_checkpoint = TaskCheckpoint(state_data={
        "memory_context": _memory(),
        "memory_audit": {"used_ids": ["missing-memory-id"]},
    })

    with pytest.raises(CompletionGateError, match="references unavailable memory IDs"):
        store.checkpoint(
            task.task_id, invalid_checkpoint, actor=task.owner,
            idempotency_key="invalid-audit", response_budget_tokens=128,
        )

    assert store.state_store.event_page(f"task:{task.task_id}")["last_seq"] == 1
    assert "memory_audit" not in store.get(task.task_id).checkpoint.state_data


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


def test_auto_worktree_preparation_failure_fails_closed_before_task_write(tmp_path, monkeypatch):
    from local_ai_hub import process_utils

    store = _store(tmp_path)
    monkeypatch.setattr(
        process_utils,
        "prepare_git_worktree",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("invalid repository")),
    )
    commits = []
    monkeypatch.setattr(store, "_commit_create", lambda *args, **kwargs: commits.append(args))

    with pytest.raises(TaskWorktreeError) as raised:
        store.create(
            _contract(), ScopeContext(), task_id="auto-create-prepare-fail", auto_worktree=True,
        )

    assert raised.value.mutation_applied is False
    assert raised.value.operation_not_started is True
    assert raised.value.outcome_unknown is False
    assert commits == []


def test_auto_worktree_git_failure_keeps_started_operation_unknown(tmp_path, monkeypatch):
    from local_ai_hub import process_utils

    store = _store(tmp_path)
    plan = SimpleNamespace(
        repo_root=str(tmp_path.resolve()), ttl_seconds=3600.0, expires_at=9999999999.0,
        response_metadata=lambda: {"success": True, "worktree_id": "worktree_000000000000"},
    )
    monkeypatch.setattr(process_utils, "prepare_git_worktree", lambda *args, **kwargs: plan)
    monkeypatch.setattr(process_utils, "create_git_worktree", lambda *args, **kwargs: {
        "success": False, "error": "git invocation timed out", "mutation_applied": None,
        "operation_not_started": False, "outcome_unknown": True,
    })
    commits = []
    monkeypatch.setattr(store, "_commit_create", lambda *args, **kwargs: commits.append(args))

    with pytest.raises(TaskWorktreeError) as raised:
        store.create(
            _contract(), ScopeContext(repository_id=str(tmp_path)), task_id="auto-create-git-fail",
            auto_worktree=True,
        )

    assert raised.value.mutation_applied is None
    assert raised.value.operation_not_started is False
    assert raised.value.outcome_unknown is True
    assert commits == []


def test_completion_returns_scheduled_worktree_cleanup_without_postcommit_write(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _mock_auto_worktree(monkeypatch, tmp_path)
    monkeypatch.setattr(store, "_verify_completion", lambda _task: None)
    created = store.create(
        _contract(), ScopeContext(repository_id=str(tmp_path)),
        task_id="complete-scheduled-cleanup", auto_worktree=True,
    )
    cleanup_calls = []
    monkeypatch.setattr(store, "cleanup_worktree", lambda *args, **kwargs: cleanup_calls.append(args))

    completed = store.complete(created.task_id, actor=created.owner)

    assert completed.status is TaskStatus.COMPLETED
    assert completed.checkpoint.state_data["worktree"]["cleanup_pending"] is True
    assert completed.checkpoint.state_data["worktree"]["cleanup_scheduled"] is True
    assert cleanup_calls == []


def test_direct_completed_transition_schedules_existing_worktree_cleanup(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _mock_auto_worktree(monkeypatch, tmp_path)
    monkeypatch.setattr(store, "_verify_completion", lambda _task: None)
    created = store.create(
        _contract(), ScopeContext(repository_id=str(tmp_path)),
        task_id="transition-scheduled-cleanup", auto_worktree=True,
    )
    active = store.transition(
        created.task_id, TaskStatus.ACTIVE, reason="activate", actor=created.owner,
        idempotency_key="activate-transition-cleanup",
    )
    verifying = store.transition(
        created.task_id, TaskStatus.VERIFYING, reason="verify", actor=created.owner,
        idempotency_key="verify-transition-cleanup",
    )

    completed = store.transition(
        created.task_id, TaskStatus.COMPLETED, reason="complete", actor=created.owner,
        idempotency_key="complete-transition-cleanup",
    )

    assert active.status is TaskStatus.ACTIVE
    assert verifying.status is TaskStatus.VERIFYING
    assert completed.status is TaskStatus.COMPLETED
    assert completed.checkpoint.state_data["worktree"]["cleanup_pending"] is True
    assert completed.checkpoint.state_data["worktree"]["cleanup_scheduled"] is True


def test_idle_reaper_accepts_scheduled_worktree_before_expiry(tmp_path, monkeypatch):
    from local_ai_hub import process_utils, worktrees

    store = _store(tmp_path)
    _mock_auto_worktree(monkeypatch, tmp_path)
    monkeypatch.setattr(store, "_verify_completion", lambda _task: None)
    created = store.create(
        _contract(), ScopeContext(repository_id=str(tmp_path)), task_id="scheduled-reaper",
        auto_worktree=True,
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


@pytest.mark.parametrize(
    "contract_data",
    [
        {"title": "legacy title", "acceptance_criteria": []},
        {"acceptance_criteria": []},
    ],
)
def test_task_projection_rejects_contract_without_canonical_goal(tmp_path, contract_data):
    store = _store(tmp_path)
    row = (
        "task-canonical-contract",
        TaskStatus.PLANNED.value,
        "agent",
        "",
        json.dumps(contract_data),
        json.dumps({}),
        json.dumps({}),
        json.dumps({}),
        0.0,
        1.0,
        1.0,
    )

    with pytest.raises(ValueError, match="task contract requires goal"):
        store._row_to_state(row)

    assert "goal" not in contract_data


@pytest.mark.parametrize("goal", [True, 7, {}, []])
def test_goal_contract_rejects_non_string_goal(goal):
    with pytest.raises(ValueError, match="goal to be a string"):
        GoalContract.from_dict({"goal": goal})


@pytest.mark.parametrize("alias", ["title", "description", "summary", "intent", "prompt", "query"])
def test_http_task_create_uses_only_canonical_goal_or_task_shortcut(alias):
    from local_ai_hub.http_server import _task_create_contract

    with pytest.raises(ValueError, match="task contract requires goal"):
        _task_create_contract({alias: "legacy task text"})

    task_contract = _task_create_contract({"task": "canonical task shorthand"})
    assert task_contract.goal == "canonical task shorthand"
    object_contract = _task_create_contract({"contract": {"goal": "canonical goal"}})
    assert object_contract.goal == "canonical goal"


def test_unsupported_completion_evaluator_fails_closed_without_project_rules(
    tmp_path, monkeypatch
):
    from local_ai_hub.agent_verification import VerificationStore
    from local_ai_hub import verification_rules

    store = _store(tmp_path)
    task = store.create(
        GoalContract(
            goal="verified task",
            acceptance_criteria=("syntax",),
            scope=AgentScope.TASK,
        ),
        ScopeContext(),
        task_id="unsupported-evaluator",
    )
    verifier = VerificationStore(store.state_store, task_store=store)
    monkeypatch.setattr(
        verifier, "completion", lambda _task_id: SimpleNamespace(complete=True)
    )
    store.verification_store = verifier
    monkeypatch.setattr(verification_rules, "_task_created_state_data", lambda *_: {})
    monkeypatch.setattr(verification_rules, "_task_project_root", lambda *_: None)

    with pytest.raises(CompletionGateError, match="verification completion evaluation failed"):
        store._verify_completion(task)


def test_completion_evaluator_receives_full_current_contract_without_project_rules(
    tmp_path, monkeypatch
):
    from local_ai_hub.agent_verification import VerificationStore
    from local_ai_hub import verification_rules

    store = _store(tmp_path)
    task = store.create(
        GoalContract(
            goal="verified task",
            acceptance_criteria=("syntax",),
            scope=AgentScope.TASK,
        ),
        ScopeContext(),
        task_id="current-evaluator-contract",
    )
    verifier = VerificationStore(store.state_store, task_store=store)
    received = {}

    def current_completion(_task_id, **kwargs):
        received.update(kwargs)
        return SimpleNamespace(complete=True)

    monkeypatch.setattr(verifier, "completion", current_completion)
    store.verification_store = verifier
    monkeypatch.setattr(verification_rules, "_task_created_state_data", lambda *_: {})
    monkeypatch.setattr(verification_rules, "_task_project_root", lambda *_: None)

    store._verify_completion(task, current_revision="revision-current")

    assert received == {
        "current_revision": "revision-current",
        "current_mutation_generation": 0,
        "verification_rules": {},
        "configured_criteria": (),
        "configured_commands": {},
        "project_config_digest": "",
        "configured_environment_sha256": {},
        "project_root": "",
    }


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
    assert "worktree" not in git_reads[0][0]
    rejected = process_utils.create_git_worktree(
        repo, branch_name="hub/task-prepared", task_id="prepared", owner="other-agent",
        created_at=1000.0, ttl_seconds=3600.0, expires_at=4600.0, prepared_plan=plan,
    )

    assert rejected["success"] is False
    assert len(git_reads) == 1

    changed_creator = {**creator, "creation_identity": 789}
    monkeypatch.setattr(process_utils, "process_identity", lambda pid: dict(changed_creator))
    identity_rejected = process_utils.create_git_worktree(
        repo, branch_name="hub/task-prepared", task_id="prepared", owner="agent",
        created_at=1000.0, ttl_seconds=3600.0, expires_at=4600.0, prepared_plan=plan,
    )

    assert identity_rejected["mutation_applied"] is False
    assert identity_rejected["operation_not_started"] is True
    assert len(git_reads) == 2
    assert all("worktree add" not in " ".join(args) for args, _kwargs in git_reads)


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
        task_memory_original_tokens,
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
    monkeypatch.setattr(mcp_server, "RESPONSE_BUDGET_ENABLED", True)

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
    assert accepted["response_budget"]["original_tokens"] == task_memory_original_tokens(success)
    assert accepted["response_budget"]["returned_tokens"] <= adequate_budget


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


def test_rollback_preflights_before_restoring_checkpoint_files(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(store, "_task_memory_context", lambda *args, **kwargs: _memory())
    task = store.create(_contract(), ScopeContext(), task_id="rollback-budget")
    target = tmp_path / "tracked.txt"
    target.write_text("before", encoding="utf-8")
    store.checkpoint(
        task.task_id,
        TaskCheckpoint(state_data={"memory_context": _memory(), "file_snapshots": {str(target): "before"}}),
        actor=task.owner,
        idempotency_key="rollback-old-checkpoint",
    )
    store.checkpoint(
        task.task_id,
        TaskCheckpoint(state_data={"memory_context": _memory(), "file_snapshots": {str(target): "after"}}),
        actor=task.owner,
        idempotency_key="rollback-current-checkpoint",
    )
    target.write_text("after", encoding="utf-8")
    monkeypatch.setattr(agent_tasks_module, "task_memory_wire_tokens", lambda projected, requested: 129)
    before_seq = store.state_store.event_page(f"task:{task.task_id}")["last_seq"]

    with pytest.raises(CheckpointResponseBudgetError):
        store.rollback(task.task_id, actor=task.owner, idempotency_key="rollback-budget", response_budget_tokens=128)

    assert target.read_text(encoding="utf-8") == "after"
    assert store.state_store.event_page(f"task:{task.task_id}")["last_seq"] == before_seq


def test_heartbeat_preflights_before_event_or_state_write(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(store, "_task_memory_context", lambda *args, **kwargs: _memory())
    task = store.create(_contract(), ScopeContext(), task_id="heartbeat-budget")
    monkeypatch.setattr(agent_tasks_module, "task_memory_wire_tokens", lambda projected, requested: 129)
    before_seq = store.state_store.event_page(f"task:{task.task_id}")["last_seq"]

    with pytest.raises(CheckpointResponseBudgetError):
        store.heartbeat(task.task_id, actor=task.owner, response_budget_tokens=128)

    assert store.state_store.event_page(f"task:{task.task_id}")["last_seq"] == before_seq


def test_resume_same_status_retry_preflights_persisted_task(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(store, "_task_memory_context", lambda *args, **kwargs: _memory())
    task = store.create(_contract(), ScopeContext(), task_id="resume-budget")
    assert task.status == TaskStatus.ACTIVE
    monkeypatch.setattr(agent_tasks_module, "task_memory_wire_tokens", lambda projected, requested: 129)
    before_seq = store.state_store.event_page(f"task:{task.task_id}")["last_seq"]

    with pytest.raises(CheckpointResponseBudgetError):
        store.resume(
            task.task_id, actor=task.owner, idempotency_key="resume-budget-retry",
            response_budget_tokens=128,
        )

    assert store.state_store.event_page(f"task:{task.task_id}")["last_seq"] == before_seq


@pytest.mark.parametrize("action", ["task_rollback", "task_resume", "task_heartbeat"])
def test_mcp_forwards_response_budget_for_remaining_full_task_mutations(monkeypatch, action):
    from local_ai_hub import mcp_server

    class RegisteredFakeClient:
        def __init__(self):
            self.requests = []

        def coord(self, **kwargs):
            self.requests.append(kwargs)
            return {"success": True, "task": {"task_id": "budget-forwarding"}}

    client = RegisteredFakeClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_: None)
    monkeypatch.setattr(mcp_server, "RESPONSE_BUDGET_ENABLED", True)

    result = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
        "action": action,
        "task_id": "budget-forwarding",
        "max_response_tokens": 512,
        "response_profile": "minimal",
    }))

    assert client.requests[-1]["action"] == action
    assert client.requests[-1]["response_budget_tokens"] == 512
    assert result


@pytest.mark.parametrize("action", ["rollback", "resume", "heartbeat"])
@pytest.mark.parametrize("failure,expected_status", [("budget", 413), ("invalid", 400)])
def test_http_mutations_map_preflight_errors(monkeypatch, action, failure, expected_status):
    from local_ai_hub import http_server

    calls = []

    def reject_budget(*args, **kwargs):
        calls.append(kwargs)
        if failure == "budget":
            raise CheckpointResponseBudgetError(128, 129)
        raise ValueError("response_budget_tokens must be a positive integer")

    task_store = SimpleNamespace(
        state_store=SimpleNamespace(enabled=True),
        rollback=reject_budget,
        resume=reject_budget,
        heartbeat=reject_budget,
    )
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(agent_tasks=task_store, recovery=None, debug_traces=None))
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *args, **kwargs: None)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/agent-state/tasks"
    handler.headers = {"Content-Type": "application/json"}
    handler._authorization_root = "."
    handler._authorization_tenant = "tenant-test"
    handler._authorization_actor = "agent"
    handler._require_authorized = lambda: True
    handler._begin_trace = lambda *_: None
    handler._claim_recovery = lambda *_: True
    handler._tenant = lambda: "tenant-test"
    handler._agent = lambda: "agent"
    handler._request_task = lambda *_args, **_kwargs: SimpleNamespace(owner="agent")
    handler._bind_task_payload = lambda _payload: True
    handler._validate_payload = lambda *_args, **_kwargs: None
    handler._read_json = lambda: {
        "action": action,
        "task_id": "budget-http",
        "response_budget_tokens": 128,
    }
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    handler.do_POST()

    assert calls[-1]["response_budget_tokens"] == 128
    status, body = responses[-1]
    assert status == expected_status
    if expected_status == 413:
        assert body["mutation_applied"] is False
        assert body["operation_not_started"] is True
        assert body["response_budget"] == {
            "requested_tokens": 128,
            "required_tokens": 129,
            "unit": "estimated_tokens",
        }
    else:
        assert body["terminal"] is True
        assert body["retryable"] is False
        assert body["error"] == "response_budget_tokens must be a positive integer"


@pytest.mark.parametrize("action", ["rollback", "resume", "heartbeat"])
@pytest.mark.parametrize("budget", [True, 0, 1.5, "128"])
def test_remaining_task_mutations_reject_noncanonical_budgets(tmp_path, action, budget):
    store = _store(tmp_path)
    task = store.create(_contract(), ScopeContext(), task_id=f"invalid-{action}-budget")
    before_seq = store.state_store.event_page(f"task:{task.task_id}")["last_seq"]

    with pytest.raises(ValueError, match="positive integer"):
        if action == "rollback":
            store.rollback(task.task_id, actor=task.owner, response_budget_tokens=budget)
        elif action == "resume":
            store.resume(
                task.task_id, actor=task.owner, idempotency_key="invalid-budget-retry",
                response_budget_tokens=budget,
            )
        else:
            store.heartbeat(task.task_id, actor=task.owner, response_budget_tokens=budget)

    assert store.state_store.event_page(f"task:{task.task_id}")["last_seq"] == before_seq

