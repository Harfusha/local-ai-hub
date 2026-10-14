from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from local_ai_hub.worktrees import (
    is_worktree_locked,
    lock_worktree,
    unlock_worktree,
    unlock_zombie_worktrees,
)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.name", "Worktree Test")
    _git(path, "config", "user.email", "worktree@example.invalid")
    _git(path, "config", "commit.gpgsign", "false")
    (path / "file1.txt").write_text("main repo\n", encoding="utf-8")
    _git(path, "add", "file1.txt")
    _git(path, "commit", "-m", "init")
    return path


def test_lock_and_unlock_worktree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "main_repo")
    wt = tmp_path / "wt1"
    _git(repo, "worktree", "add", "-b", "branch1", str(wt))

    locked, reason = is_worktree_locked(repo, wt)
    assert locked is False

    ok = lock_worktree(repo, wt, reason="testing lock", pid=os.getpid())
    assert ok is True

    locked, reason = is_worktree_locked(repo, wt)
    assert locked is True
    assert "testing lock" in reason

    unlocked = unlock_worktree(repo, wt)
    assert unlocked is True
    assert is_worktree_locked(repo, wt)[0] is False


def test_unlock_zombie_worktrees_prunes_dead_pid(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "main_repo")
    wt = tmp_path / "wt_dead"
    _git(repo, "worktree", "add", "-b", "branch_dead", str(wt))

    # Lock with a dead PID (e.g. 99999999)
    dead_pid = 99999999
    lock_worktree(repo, wt, reason="orphaned job", pid=dead_pid)
    assert is_worktree_locked(repo, wt)[0] is True

    reaped = unlock_zombie_worktrees(repo)
    assert len(reaped) == 1
    assert reaped[0]["worktree"] == "wt_dead"
    assert reaped[0]["status"] == "unlocked"
    assert reaped[0]["pid"] == dead_pid

    # Verified unlocked in git
    assert is_worktree_locked(repo, wt)[0] is False


def test_unlock_zombie_worktrees_preserves_live_pid(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "main_repo")
    wt = tmp_path / "wt_live"
    _git(repo, "worktree", "add", "-b", "branch_live", str(wt))

    # Lock with current live process PID
    lock_worktree(repo, wt, reason="active process", pid=os.getpid())
    assert is_worktree_locked(repo, wt)[0] is True

    reaped = unlock_zombie_worktrees(repo)
    assert len(reaped) == 0  # Not reaped because process is alive

    assert is_worktree_locked(repo, wt)[0] is True
