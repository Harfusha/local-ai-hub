from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub.worktrees import (
    check_worktree_uncommitted_changes,
    get_worktree_status,
    is_git_worktree,
    remove_worktree_safe,
    switch_worktree_branch,
    unlock_worktree,
    unlock_zombie_worktrees,
)
from local_ai_hub import worktrees


def _init_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "main_repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("initial commit\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "branch", "branch-a"], cwd=repo, check=True, capture_output=True)

    wt = tmp_path / "wt_work"
    subprocess.run(["git", "worktree", "add", "-b", "wt-branch", str(wt), "HEAD"], cwd=repo, check=True, capture_output=True)
    return repo, wt


def test_get_worktree_status_and_is_git_worktree(tmp_path: Path) -> None:
    repo, wt = _init_repo(tmp_path)

    # is_git_worktree checks
    assert is_git_worktree(wt) is True
    assert is_git_worktree(tmp_path) is False
    assert is_git_worktree(tmp_path / "nonexistent") is False

    # Clean status
    status = get_worktree_status(wt)
    assert status["exists"] is True
    assert status["clean"] is True
    assert status["uncommitted_files"] == []
    assert status["branch"] == "wt-branch"
    assert status["locked"] is False

    # Create uncommitted file
    (wt / "file.py").write_text("print(1)\n", encoding="utf-8")
    status_dirty = get_worktree_status(wt)
    assert status_dirty["clean"] is False
    assert len(status_dirty["uncommitted_files"]) > 0
    assert any("file.py" in f for f in status_dirty["uncommitted_files"])


def test_check_worktree_uncommitted_changes_invalid_path(tmp_path: Path) -> None:
    # Non-existent path returns (False, "worktree_not_found")
    clean, err = check_worktree_uncommitted_changes(tmp_path / "does_not_exist")
    assert clean is False
    assert err == "worktree_not_found"

    # Non-existent path with force=True returns True
    clean_forced, err_forced = check_worktree_uncommitted_changes(tmp_path / "does_not_exist", force=True)
    assert clean_forced is True
    assert err_forced == ""


def test_unlock_fallback_never_unlinks_outside_common_dir(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    common = tmp_path / "common"
    outside = tmp_path / "outside"
    repo.mkdir()
    common.mkdir()
    outside.mkdir()
    unrelated_lock = outside / "locked"
    unrelated_lock.write_text("keep", encoding="utf-8")
    calls = 0

    def fake_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return SimpleNamespace(returncode=1, stdout="", stderr="not a worktree")
        return SimpleNamespace(returncode=0, stdout=str(common), stderr="")

    monkeypatch.setattr(worktrees.subprocess, "run", fake_run)
    assert unlock_worktree(repo, outside) is False
    assert unrelated_lock.read_text(encoding="utf-8") == "keep"
