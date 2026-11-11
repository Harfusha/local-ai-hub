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


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_get_worktree_status_and_is_git_worktree(tmp_path: Path, monkeypatch) -> None:
    repo, wt = _init_repo(tmp_path)

    # is_git_worktree checks
    assert is_git_worktree(wt) is True
    assert is_git_worktree(tmp_path) is False
    assert is_git_worktree(tmp_path / "nonexistent") is False

    # Lock inspection runs Git from the worktree whose status it reports.
    original_run = worktrees.subprocess.run
    list_cwds = []

    def track_worktree_list(command, *args, **kwargs):
        if command[-3:] == ["worktree", "list", "--porcelain"]:
            list_cwds.append(command[command.index("-C") + 1])
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(worktrees.subprocess, "run", track_worktree_list)

    # Clean status
    status = get_worktree_status(wt)
    assert status["exists"] is True
    assert status["clean"] is True
    assert status["uncommitted_files"] == []
    assert status["branch"] == "wt-branch"
    assert status["locked"] is False
    assert status["lock_status"] == "unlocked"
    assert list_cwds == [str(wt.resolve())]

    # Create uncommitted file
    (wt / "file.py").write_text("print(1)\n", encoding="utf-8")
    status_dirty = get_worktree_status(wt)
    assert status_dirty["clean"] is False
    assert len(status_dirty["uncommitted_files"]) > 0
    assert any("file.py" in f for f in status_dirty["uncommitted_files"])


def test_get_worktree_status_reports_unknown_when_git_lock_query_fails(
    tmp_path: Path, monkeypatch
) -> None:
    _, wt = _init_repo(tmp_path)
    original_run = worktrees.subprocess.run

    def fail_worktree_list(command, *args, **kwargs):
        if command[-3:] == ["worktree", "list", "--porcelain"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="git unavailable")
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(worktrees.subprocess, "run", fail_worktree_list)
    status = get_worktree_status(wt)

    assert status["locked"] is None
    assert status["lock_status"] == "unknown"


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


def test_unlock_fallback_refuses_basename_collision(tmp_path: Path) -> None:
    repo, _ = _init_repo(tmp_path)
    decoy = tmp_path / "decoy" / "collision"
    decoy.mkdir(parents=True)
    common = Path(_git(repo, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = (repo / common).resolve()
    lock = common / "worktrees" / decoy.name / "locked"
    lock.parent.mkdir(parents=True)
    lock.write_text("unrelated lock", encoding="utf-8")

    assert unlock_worktree(repo, decoy) is False
    assert lock.read_text(encoding="utf-8") == "unrelated lock"


def test_unlock_fallback_uses_exact_worktree_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    repo, wt = _init_repo(tmp_path)
    assert worktrees.lock_worktree(repo, wt, reason="test lock") is True
    git_dir = Path(_git(wt, "rev-parse", "--absolute-git-dir"))
    lock = git_dir / "locked"
    assert lock.is_file()
    original_run = worktrees.subprocess.run

    def fail_git_unlock(command, *args, **kwargs):
        if command[2:4] == ["worktree", "unlock"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="fallback test")
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(worktrees.subprocess, "run", fail_git_unlock)
    assert unlock_worktree(repo, wt) is True
    assert lock.exists() is False


def test_unlock_zombie_refuses_mismatched_admin_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    repo, wt = _init_repo(tmp_path)
    other_wt = tmp_path / "other_worktree"
    _git(repo, "worktree", "add", "-b", "other-branch", str(other_wt), "HEAD")
    assert worktrees.lock_worktree(repo, wt, reason="stale lock", pid=99999999)

    git_dir = Path(_git(wt, "rev-parse", "--absolute-git-dir"))
    (git_dir / "gitdir").write_text(str(other_wt / ".git"), encoding="utf-8")
    monkeypatch.setattr(worktrees, "pid_alive", lambda _pid: False)

    assert unlock_zombie_worktrees(repo) == []
    assert (git_dir / "locked").is_file()
