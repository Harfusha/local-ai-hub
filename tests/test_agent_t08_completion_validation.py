from __future__ import annotations

from pathlib import Path
import subprocess
import sys
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
from local_ai_hub.agent_verification import VerificationStore
from local_ai_hub.commands import CommandBroker


def _task_with_memory(tmp_path, task_id: str, monkeypatch, *, audited: bool = True):
    repository_root = tmp_path.resolve()
    (repository_root / ".local-ai.toml").write_text(
        '[commands.test]\nargv = ["python", "-B", "-c", "print(1)"]\n',
        encoding="utf-8",
    )
    (repository_root / "test_completion.py").write_text(
        "def test_completion_evidence():\n    assert True\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "--quiet"], cwd=repository_root, check=True)
    subprocess.run(["git", "config", "user.name", "Hub test"], cwd=repository_root, check=True)
    subprocess.run(["git", "config", "user.email", "hub-test@example.invalid"], cwd=repository_root, check=True)
    subprocess.run(["git", "add", ".local-ai.toml", "test_completion.py"], cwd=repository_root, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "initialize receipt fixture"], cwd=repository_root, check=True)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repository_root, check=True, text=True, capture_output=True
    ).stdout.strip()
    coordination_id = "repo:t08-completion-validation"
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
            "schema_version": 2,
            "context": {
                "root": str(repository_root),
                "coordination_id": coordination_id,
                "task_id": task_id,
                "session_id": "",
                "clone_id": "",
                "worktree_id": "",
                "branch": "",
            },
            "instruction": "Use memory carefully",
            "items": [{"id": "mem-1", "volatile": False}],
            "warnings": [],
            "estimated_tokens": 1,
        },
    )
    task = tasks.create(
        GoalContract(goal="validate completion", acceptance_criteria=("tests",)),
        ScopeContext(repository_id=coordination_id, task_id=task_id),
        task_id=task_id,
        actor="test-agent",
        repo_root=str(repository_root),
        repository_revision=revision,
    )
    state_data = {"repository_revision": revision, "mutation_generation": 0}
    if audited:
        state_data["memory_audit"] = {"used_ids": ["mem-1"]}
    checkpoint = TaskCheckpoint(state_data=state_data)
    if audited:
        tasks.checkpoint(
            task.task_id, checkpoint, actor="test",
            idempotency_key=f"{task_id}-receipt-context",
        )
    else:
        before = tasks.get(task.task_id)
        before_events = state.events(f"task:{task.task_id}")
        with pytest.raises(CompletionGateError, match="requires checkpoint memory_audit"):
            tasks.checkpoint(task.task_id, checkpoint, actor="test")
        assert tasks.get(task.task_id) == before
        assert state.events(f"task:{task.task_id}") == before_events
        # Seed pre-gate stored state only; restore enforcement before completion.
        with monkeypatch.context() as legacy_fixture:
            legacy_fixture.setattr(tasks, "_validate_memory_audit", lambda _task: None)
            tasks.checkpoint(
                task.task_id, checkpoint, actor="test",
                idempotency_key=f"{task_id}-receipt-context",
            )
    broker = CommandBroker(
        {
            "commands": {"enabled": True, "allow_read": True, "allow_validation": True},
            "server": {"state_dir": str(tmp_path / "command-state")},
        },
        artifacts,
        type(
            "_RepoState",
            (),
            {
                "fingerprint": lambda _self, cwd: {
                    "fingerprint": subprocess.run(
                        ["git", "rev-parse", "HEAD"],
                        cwd=cwd,
                        check=True,
                        text=True,
                        capture_output=True,
                    ).stdout.strip(),
                    "root": str(cwd),
                }
            },
        )(),
    )
    broker.set_task_store(tasks)
    broker.set_verification_store(verifier)
    verifier.set_command_execution_record_lookup(broker.get_command_execution_record)
    result = broker.run(
        f'"{sys.executable}" -B -m pytest -q test_completion.py',
        str(repository_root),
        timeout=60,
        task_id=task.task_id,
        criterion="tests",
    )
    assert result.get("success") is True, result.get("error")
    assert isinstance(result.get("verification_receipt"), dict)
    return state, tasks, task


def test_validate_completion_rejects_missing_memory_audit_without_transition(
    tmp_path, monkeypatch
):
    state, tasks, task = _task_with_memory(
        tmp_path, "validate-memory-audit", monkeypatch, audited=False
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
    tasks.transition(
        task.task_id,
        TaskStatus.ACTIVE,
        reason="start",
        actor="test-agent",
        idempotency_key="activate",
    )
    tasks.transition(
        task.task_id,
        TaskStatus.VERIFYING,
        reason="ready",
        actor="test-agent",
        idempotency_key="verify",
    )

    completed = tasks.transition(
        task.task_id,
        TaskStatus.COMPLETED,
        reason="verified",
        actor="test-agent",
        idempotency_key="complete",
    )

    assert completed.status is TaskStatus.COMPLETED
    assert state.events(f"task:{task.task_id}")[-1].kind == "task.transitioned"
