import subprocess
from pathlib import Path
import pytest

from local_ai_hub.worktrees import (
    check_worktree_uncommitted_changes,
    switch_worktree_branch,
    remove_worktree_safe,
)
from local_ai_hub.process_utils import remove_git_worktree


def _init_repo_with_worktree(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "main_repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo, check=True, capture_output=True)
    
    (repo / "README.md").write_text("initial commit\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "branch", "feature-branch"], cwd=repo, check=True, capture_output=True)

    wt = tmp_path / "wt_test"
    subprocess.run(["git", "worktree", "add", "-b", "wt-branch", str(wt), "HEAD"], cwd=repo, check=True, capture_output=True)
    return repo, wt


def test_guard_detects_dirty_worktree(tmp_path: Path):
    repo, wt = _init_repo_with_worktree(tmp_path)
    
    # Clean worktree
    clean, err = check_worktree_uncommitted_changes(wt)
    assert clean is True
    assert err == ""

    # Dirty worktree (untracked file)
    (wt / "dirty.txt").write_text("uncommitted content", encoding="utf-8")
    clean, err = check_worktree_uncommitted_changes(wt)
    assert clean is False
    assert err == "uncommitted_changes_in_worktree"

    # Forced bypass
    clean_forced, err_forced = check_worktree_uncommitted_changes(wt, force=True)
    assert clean_forced is True
    assert err_forced == ""


def test_switch_branch_fails_on_uncommitted_changes(tmp_path: Path):
    repo, wt = _init_repo_with_worktree(tmp_path)
    (wt / "dirty_edit.txt").write_text("in progress work", encoding="utf-8")

    res = switch_worktree_branch(wt, "feature-branch")
    assert res["success"] is False
    assert res["error"] == "uncommitted_changes_in_worktree"
    assert (wt / "dirty_edit.txt").exists()

    # Forced switch succeeds
    res_forced = switch_worktree_branch(wt, "feature-branch", force=True)
    assert res_forced["success"] is True


def test_remove_worktree_fails_on_uncommitted_changes(tmp_path: Path):
    repo, wt = _init_repo_with_worktree(tmp_path)
    (wt / "critical_data.txt").write_text("do not delete me", encoding="utf-8")

    res = remove_worktree_safe(repo, wt)
    assert res["success"] is False
    assert res["error"] == "uncommitted_changes_in_worktree"
    assert wt.exists()
    assert (wt / "critical_data.txt").exists()

    # Forced remove succeeds
    res_forced = remove_worktree_safe(repo, wt, force=True)
    assert res_forced["success"] is True
    assert not wt.exists()
