from __future__ import annotations

import inspect

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import (
    CompletionGateError,
    GoalContract,
    TaskCheckpoint,
    TaskStatus,
    TaskStore,
)
from local_ai_hub.agent_verification import VerificationReceipt, VerificationStore


def _task_with_memory(tmp_path, task_id: str, monkeypatch):
    state = AgentStateStore(tmp_path / "agent_state.sqlite3")
    tasks = TaskStore(state)
    artifacts = ArtifactStore(tmp_path / "artifacts")
    verifier = VerificationStore(state, task_store=tasks)
    verifier.artifact_store = artifacts
    tasks.verification_store = verifier
    monkeypatch.setattr(
        tasks,
        "_task_memory_context",
        lambda *_args, **_kwargs: {
            "items": [{"id": "mem-1", "volatile": False}],
            "warnings": [],
        },
    )
    task = tasks.create(
        GoalContract(goal="validate completion", acceptance_criteria=("tests",)),
        ScopeContext(task_id=task_id),
        task_id=task_id,
        actor="test",
    )
    tasks.checkpoint(
        task.task_id,
        TaskCheckpoint(state_data={"repository_revision": "rev-1", "mutation_generation": 0}),
        actor="test",
        idempotency_key=f"{task_id}-receipt-context",
    )
    command_id = f"cmd-{task_id}"
    receipt_owner = task.owner
    evidence_id = "tests-evidence"
    if "owner" in inspect.signature(VerificationReceipt.create).parameters:
        proof = {
            "kind": "work_command_verification",
            "passed": True,
            "task_id": task.task_id,
            "owner": receipt_owner,
            "criterion": "tests",
            "command_id": command_id,
            "command_classification": "test",
            "command": "python -m pytest -q",
            "repository_revision": "rev-1",
            "mutation_generation": 0,
            "exit_code": 0,
            "cached": False,
            "result": {"success": True, "exit_code": 0},
        }
        evidence_id = artifacts.put_json(proof, receipt_owner, "command_verification")
    receipt_kwargs = {
        "passed": True,
        "evidence_id": evidence_id,
        "command_id": command_id,
    }
    supported = inspect.signature(VerificationReceipt.create).parameters
    for key, value in {
        "owner": receipt_owner,
        "repository_revision": "rev-1",
        "mutation_generation": 0,
        "evidence_type": "test",
    }.items():
        if key in supported:
            receipt_kwargs[key] = value
    receipt = VerificationReceipt.create(task.task_id, "tests", **receipt_kwargs)
    verifier.record(receipt)
    return state, tasks, task


def test_validate_completion_rejects_missing_memory_audit_without_transition(
    tmp_path, monkeypatch
):
    state, tasks, task = _task_with_memory(
        tmp_path, "validate-memory-audit", monkeypatch
    )
    before = tasks.get(task.task_id)
    before_events = state.events(f"task:{task.task_id}")

    with pytest.raises(CompletionGateError, match="requires checkpoint memory_audit"):
        tasks.validate_completion(task.task_id)

    after = tasks.get(task.task_id)
    assert after == before
    assert after.status is TaskStatus.PLANNED
    assert state.events(f"task:{task.task_id}") == before_events


def test_validate_completion_accepts_audited_memory_and_persisted_receipt_without_transition(
    tmp_path, monkeypatch
):
    state, tasks, task = _task_with_memory(
        tmp_path, "validate-audited-completion", monkeypatch
    )
    tasks.checkpoint(
        task.task_id,
        TaskCheckpoint(
            state_data={"memory_audit": {"used_ids": ["mem-1"]}}
        ),
        actor="test",
    )
    before = tasks.get(task.task_id)
    before_events = state.events(f"task:{task.task_id}")

    validated = tasks.validate_completion(task.task_id)

    assert validated == before
    assert validated.status is TaskStatus.PLANNED
    assert state.events(f"task:{task.task_id}") == before_events


def test_terminal_transition_accepts_valid_memory_audit_and_persisted_receipt(
    tmp_path, monkeypatch
):
    state, tasks, task = _task_with_memory(
        tmp_path, "terminal-valid-memory-completion", monkeypatch
    )
    tasks.checkpoint(
        task.task_id,
        TaskCheckpoint(state_data={"memory_audit": {"used_ids": ["mem-1"]}}),
        actor="test",
    )
    tasks.transition(
        task.task_id,
        TaskStatus.ACTIVE,
        reason="start",
        actor="test",
        idempotency_key="activate",
    )
    tasks.transition(
        task.task_id,
        TaskStatus.VERIFYING,
        reason="ready",
        actor="test",
        idempotency_key="verify",
    )

    completed = tasks.transition(
        task.task_id,
        TaskStatus.COMPLETED,
        reason="verified",
        actor="test",
        idempotency_key="complete",
    )

    assert completed.status is TaskStatus.COMPLETED
    assert state.events(f"task:{task.task_id}")[-1].kind == "task.transitioned"
