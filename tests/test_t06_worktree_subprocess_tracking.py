from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import pytest

from local_ai_hub import process_utils


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def test_git_worktree_lifecycle_uses_tracked_subprocess_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "T06 test")
    _git(repo, "config", "user.email", "t06@example.invalid")
    (repo / "tracked.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-qm", "seed")

    tracked: list[tuple[str, ...]] = []
    original_run_hidden = process_utils.run_hidden
    original_subprocess_run = subprocess.run

    def observe_run_hidden(argv, **kwargs):
        tracked.append(tuple(str(part) for part in argv))
        return original_run_hidden(argv, **kwargs)

    def reject_untracked_subprocess(*_args, **_kwargs):
        raise AssertionError("worktree helper bypassed tracked process runner")

    monkeypatch.setattr(process_utils, "run_hidden", observe_run_hidden)
    monkeypatch.setattr(process_utils.subprocess, "run", reject_untracked_subprocess)

    branch = f"t06-route-{uuid.uuid4().hex[:8]}"
    target = tmp_path / "isolated-worktree"
    created = process_utils.create_git_worktree(
        repo,
        branch_name=branch,
        worktree_path=target,
        base_commit="HEAD",
        task_id="task-t06",
        owner="t06-test",
    )
    assert created["success"] is True, created

    removed = process_utils.remove_git_worktree(
        repo,
        target,
        worktree_id=created["worktree_id"],
        branch_name=branch,
    )
    assert removed["success"] is True, removed
    pruned = process_utils.prune_git_worktrees(repo)
    assert pruned["success"] is True, pruned
    assert any("worktree" in call and "add" in call for call in tracked)
    assert any("status" in call for call in tracked)
    assert any("worktree" in call and "remove" in call for call in tracked)
    assert any("worktree" in call and "prune" in call for call in tracked)
    assert any("worktree" in call and "prune" in call and "-v" in call for call in tracked)
    assert any("branch" in call and "-d" in call for call in tracked)
    assert not target.exists()
    # Preserve fixture setup API for teardown diagnostics if a future edit fails.
    assert callable(original_subprocess_run)

