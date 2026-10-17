from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from local_ai_hub import process_utils
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope, ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskCheckpoint, TaskStore


@pytest.mark.parametrize("tamper_path", [False, True])
def test_cleanup_reconciles_removed_worktree_after_completion_checkpoint_failure(tmp_path, monkeypatch, tamper_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    store = TaskStore(AgentStateStore(tmp_path / "agent-state.sqlite3"))
    monkeypatch.setattr(
        process_utils, "prepare_git_worktree",
        lambda root, **kwargs: type("Plan", (), {
            "repo_root": str(repo),
            "ttl_seconds": 3600.0,
            "expires_at": 9999999999.0,
            "response_metadata": lambda self: {
                "success": True,
                "lease_id": "lease_000000000001",
                "worktree_id": "worktree_000000000001",
                "worktree_path": str(tmp_path / "scheduled-worktree"),
                "branch": "agent/test-cleanup",
                "base_commit": "a" * 40,
                "repo_root": str(repo),
                "task_id": kwargs["task_id"],
                "owner": kwargs["owner"],
                "created_at": kwargs["created_at"],
                "ttl_seconds": kwargs["ttl_seconds"],
                "expires_at": kwargs["expires_at"],
                "creator_pid": 1,
                "creator_creation_identity": 2,
                "creator_creation_identity_type": "test",
                "creator_executable": "python.exe",
            },
        })(),
    )
    monkeypatch.setattr(
        process_utils, "create_git_worktree",
        lambda _root, **kwargs: kwargs["prepared_plan"].response_metadata(),
    )
    task = store.create(
        GoalContract(goal="cleanup retry", acceptance_criteria=(), scope=AgentScope.TASK),
        ScopeContext(repository_id=str(repo)), task_id="cleanup-retry", auto_worktree=True,
    )
    worktree = Path(task.checkpoint.state_data["worktree"]["worktree_path"])
    worktree.mkdir()
    ownership = dict(task.checkpoint.state_data["worktree"])
    monkeypatch.setattr(process_utils, "get_git_worktree_ownership", lambda *_a, **_k: ownership)
    removed = []

    def remove(_repo, target, **kwargs):
        shutil.rmtree(target)
        removed.append(kwargs["worktree_id"])
        return {"success": True, "worktree_removed": True, "branch_deleted": True}

    monkeypatch.setattr(process_utils, "remove_git_worktree", remove)
    verify_calls = []
    monkeypatch.setattr(
        process_utils, "verify_git_worktree_cleanup_complete",
        lambda *_a, **_k: verify_calls.append(True) or {"success": True},
        raising=False,
    )
    real_checkpoint = store.checkpoint

    def fail_final_checkpoint(task_id, checkpoint, **kwargs):
        if checkpoint.state_data["worktree"].get("cleanup_success"):
            raise OSError("injected checkpoint persistence failure")
        return real_checkpoint(task_id, checkpoint, **kwargs)

    monkeypatch.setattr(store, "checkpoint", fail_final_checkpoint)
    first = store.cleanup_worktree(task.task_id, actor=task.owner)

    assert first["success"] is False
    assert removed == ["worktree_000000000001"]
    assert not worktree.exists()
    assert store.get(task.task_id).checkpoint.state_data["worktree"]["cleanup_intent"]["worktree_id"] == "worktree_000000000001"
    if tamper_path:
        persisted = store.get(task.task_id)
        changed_worktree = {
            **persisted.checkpoint.state_data["worktree"],
            "worktree_path": str(tmp_path / "substituted-missing-path"),
        }
        changed_checkpoint = TaskCheckpoint(
            phase=persisted.checkpoint.phase,
            next_action=persisted.checkpoint.next_action,
            affected_paths=persisted.checkpoint.affected_paths,
            evidence_ids=persisted.checkpoint.evidence_ids,
            blockers=persisted.checkpoint.blockers,
            state_data={**persisted.checkpoint.state_data, "worktree": changed_worktree},
        )
        real_checkpoint(task.task_id, changed_checkpoint, actor=task.owner, idempotency_key="tamper-cleanup-path")

    monkeypatch.setattr(process_utils, "get_git_worktree_ownership", lambda *_a, **_k: None)
    monkeypatch.setattr(store, "checkpoint", real_checkpoint)
    second = store.cleanup_worktree(task.task_id, actor=task.owner)

    if tamper_path:
        assert second["success"] is False
        assert "intent does not match" in second["error"]
        assert verify_calls == []
        assert store.get(task.task_id).checkpoint.state_data["worktree"].get("cleanup_success") is None
        return

    assert second["success"] is True
    assert second["already_cleaned"] is True
    assert verify_calls == [True]
    assert store.get(task.task_id).checkpoint.state_data["worktree"]["cleanup_success"] is True
