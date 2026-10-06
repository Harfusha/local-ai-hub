from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import (
    CompletionGateError,
    GoalContract,
    TaskCheckpoint,
    TaskState,
    TaskStatus,
)
from local_ai_hub.agent_verification import VerificationReceipt
from local_ai_hub.app import LocalAIApp
from local_ai_hub import process_utils
from local_ai_hub.verification_rules import (
    _task_project_root,
    complete_task_with_project_rules,
)


def test_auto_worktree_path_is_task_project_root_over_source_and_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source_root = tmp_path / "source"
    worktree_root = tmp_path / "task-worktree"
    source_root.mkdir()
    worktree_root.mkdir()
    ownership = {
        "schema_version": 1,
        "task_id": "task-worktree-root",
        "owner": "agent",
        "worktree_id": "worktree-owned",
        "repo_root": str(source_root),
        "worktree_path": str(worktree_root),
        "branch": "hub/task-worktree-root",
    }
    ownership_path = tmp_path / "worktree-ownership.json"
    ownership_path.write_text(json.dumps(ownership), encoding="utf-8")
    monkeypatch.setattr(
        process_utils,
        "_worktree_ownership_path",
        lambda _path: ownership_path,
        raising=False,
    )
    task = TaskState(
        task_id="task-worktree-root",
        status=TaskStatus.PLANNED,
        contract=GoalContract(goal="bind task project root"),
        context=ScopeContext(repository_id=str(source_root), task_id="task-worktree-root"),
        owner="agent",
        checkpoint=TaskCheckpoint(
            state_data={
                "repo_root": str(source_root),
                "worktree": {
                    "repo_root": str(source_root),
                    "worktree_path": str(worktree_root),
                    "task_id": "task-worktree-root",
                    "owner": "agent",
                    "worktree_id": "worktree-owned",
                    "branch": "hub/task-worktree-root",
                },
            }
        ),
    )

    assert _task_project_root(task) == worktree_root.resolve()


def test_unowned_checkpoint_worktree_path_falls_back_to_physical_context(tmp_path: Path):
    source_root = tmp_path / "source"
    attacker_root = tmp_path / "unowned-worktree"
    source_root.mkdir()
    attacker_root.mkdir()
    task = TaskState(
        task_id="task-unowned-worktree-root",
        status=TaskStatus.PLANNED,
        contract=GoalContract(goal="reject unowned checkpoint worktree"),
        context=ScopeContext(
            repository_id=str(source_root), task_id="task-unowned-worktree-root"
        ),
        owner="agent",
        checkpoint=TaskCheckpoint(
            state_data={
                "worktree": {
                    "repo_root": str(source_root),
                    "worktree_path": str(attacker_root),
                    "task_id": "task-unowned-worktree-root",
                    "owner": "agent",
                    "worktree_id": "forged-id",
                    "branch": "hub/task-unowned-worktree-root",
                },
            }
        ),
    )

    assert _task_project_root(task) == source_root.resolve()


def test_checkpoint_root_tampering_cannot_replace_trusted_task_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    trusted_root = tmp_path / "trusted-project"
    attacker_root = tmp_path / "attacker-project"
    trusted_root.mkdir()
    attacker_root.mkdir()
    (trusted_root / ".local-ai.toml").write_text(
        '[commands]\nlint = "python -m ruff check src"\n'
        '[verification_rules]\nrequired_commands = ["lint"]\n',
        encoding="utf-8",
    )
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config_path = tmp_path / "hub.toml"
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11498\nstate_dir = "{state_dir.as_posix()}"\n'
        "\n[agent_state]\nenabled = true\n",
        encoding="utf-8",
    )

    app = LocalAIApp(str(config_path))
    task_id = "checkpoint-root-tampering"
    try:
        app.agent_tasks.create(
            GoalContract(
                goal="keep completion bound to trusted task root",
                acceptance_criteria=("required_commands",),
            ),
            ScopeContext(task_id=task_id, repository_id=str(trusted_root)),
            task_id=task_id,
            actor="agent",
            repo_root=str(trusted_root),
        )
        app.agent_tasks.checkpoint(
            task_id,
            TaskCheckpoint(
                phase="verification",
                state_data={
                    "mutation_generation": 0,
                    "repo_root": str(attacker_root),
                },
            ),
            actor="agent",
        )
        before = app.agent_tasks.get(task_id)
        assert before is not None
        events_before = app.agent_state.events(stream_id=f"task:{task_id}")
        completion_calls = []

        def accept_if_reached(*args, **kwargs):
            completion_calls.append((args, kwargs))
            return SimpleNamespace(
                complete=True,
                unsatisfied_criteria=(),
                stale_criteria=(),
            )

        monkeypatch.setattr(app.agent_verification, "completion", accept_if_reached)
        with pytest.raises(CompletionGateError, match="does not match task project root"):
            complete_task_with_project_rules(
                app.agent_tasks,
                app.agent_verification,
                task_id,
                root=attacker_root,
                state_dir=state_dir,
                current_revision="rev-trusted",
                actor="agent",
            )

        after = app.agent_tasks.get(task_id)
        assert completion_calls == []
        assert after is not None and after.checkpoint == before.checkpoint
        assert after.status == TaskStatus.PLANNED
        assert app.agent_state.events(stream_id=f"task:{task_id}") == events_before
    finally:
        app.close()


def test_direct_task_complete_cannot_use_checkpoint_root_to_drop_lint_rule(
    tmp_path: Path,
):
    trusted_root = tmp_path / "trusted-project"
    attacker_root = tmp_path / "attacker-project"
    trusted_root.mkdir()
    attacker_root.mkdir()
    (trusted_root / ".local-ai.toml").write_text(
        '[commands]\ntest = "python -m pytest -q"\n'
        'lint = "python -m ruff check src"\n'
        '[verification_rules]\ntest = ["test", "lint"]\n',
        encoding="utf-8",
    )
    (attacker_root / ".local-ai.toml").write_text(
        '[commands]\ntest = "python -m pytest -q"\n'
        '[verification_rules]\ntest = ["test"]\n',
        encoding="utf-8",
    )
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config_path = tmp_path / "hub.toml"
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11498\nstate_dir = "{state_dir.as_posix()}"\n'
        "\n[agent_state]\nenabled = true\n",
        encoding="utf-8",
    )

    app = LocalAIApp(str(config_path))
    task_id = "direct-complete-checkpoint-root-tampering"
    try:
        app.agent_tasks.create(
            GoalContract(
                goal="retain trusted lint requirement",
                acceptance_criteria=("test",),
            ),
            ScopeContext(task_id=task_id, repository_id=str(trusted_root)),
            task_id=task_id,
            actor="agent",
            repo_root=str(trusted_root),
        )
        attacker_proof = app.artifacts.put_json(
            {
                "kind": "work_command_verification",
                "passed": True,
                "task_id": task_id,
                "owner": "agent",
                "repository_revision": "rev-root-binding",
                "mutation_generation": 0,
                "criterion": "test",
                "command_id": "cmd-root-binding-test",
                "command_classification": "test",
                "exit_code": 0,
                "result": {"success": True, "exit_code": 0},
            },
            "agent",
            "command_verification",
        )
        app.agent_verification.record(
            VerificationReceipt.create(
                task_id,
                "test",
                evidence_id=attacker_proof,
                command_id="cmd-root-binding-test",
                owner="agent",
                repository_revision="rev-root-binding",
                evidence_type="test",
            )
        )
        task = app.agent_tasks.get(task_id)
        assert task is not None
        state_data = dict(task.checkpoint.state_data)
        state_data["repo_root"] = str(attacker_root)
        state_data["repository_revision"] = "rev-root-binding"
        app.agent_tasks.checkpoint(
            task_id,
            TaskCheckpoint(phase="verification", state_data=state_data),
            actor="agent",
        )
        before = app.agent_tasks.get(task_id)
        assert before is not None
        events_before = app.agent_state.events(stream_id=f"task:{task_id}")

        with pytest.raises(
        CompletionGateError, match="criterion 'lint'"
        ) as rejected:
            app.agent_tasks.complete(task_id, actor="agent")
        assert "lint" in str(rejected.value)

        after = app.agent_tasks.get(task_id)
        assert after is not None and after.status == TaskStatus.PLANNED
        assert after.checkpoint == before.checkpoint
        assert app.agent_state.events(stream_id=f"task:{task_id}") == events_before

        active = app.agent_tasks.transition(
            task_id,
            TaskStatus.ACTIVE,
            reason="prepare direct transition regression",
            actor="agent",
            idempotency_key="activate-before-direct-transition",
        )
        verifying = app.agent_tasks.transition(
            task_id,
            TaskStatus.VERIFYING,
            reason="prepare final transition regression",
            actor="agent",
            idempotency_key="verify-before-direct-transition",
        )
        transition_events = app.agent_state.events(stream_id=f"task:{task_id}")
        with pytest.raises(CompletionGateError, match="criterion 'lint'") as direct_rejected:
            app.agent_tasks.transition(
                task_id,
                TaskStatus.COMPLETED,
                reason="must keep lint rule",
                actor="agent",
                idempotency_key="direct-transition-root-binding",
            )
        assert "lint" in str(direct_rejected.value)
        unchanged = app.agent_tasks.get(task_id)
        assert unchanged is not None and unchanged.status == TaskStatus.VERIFYING
        assert unchanged.checkpoint == verifying.checkpoint
        assert app.agent_state.events(stream_id=f"task:{task_id}") == transition_events
    finally:
        app.close()
