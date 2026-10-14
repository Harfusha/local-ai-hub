from __future__ import annotations

import tempfile
from pathlib import Path

from local_ai_hub import worktrees


def test_is_hub_temporary_worktree_validations(tmp_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="lah_wt_test_valid_") as raw:
        valid_dir = Path(raw)
        assert worktrees.is_hub_temporary_worktree(valid_dir) is True

    # Wrong prefix
    with tempfile.TemporaryDirectory(prefix="other_prefix_test_") as raw:
        non_wt = Path(raw)
        assert worktrees.is_hub_temporary_worktree(non_wt) is False

    # Non-existent
    assert worktrees.is_hub_temporary_worktree(tmp_path / "lah_wt_nonexistent_123") is False


def test_discover_worktree_roots_handles_non_directory_and_path_objects(tmp_path: Path) -> None:
    non_dir = tmp_path / "not_a_dir"
    # Should exit early and return empty list
    assert worktrees.discover_worktree_roots(non_dir) == []
    assert worktrees.discover_worktree_roots(str(non_dir)) == []


def test_worktree_is_clean_ancestor_validates_inputs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    wt = tmp_path / "wt"

    # Non-existent directories
    ok, reason = worktrees.worktree_is_clean_ancestor(repo, wt, "abc1234")
    assert ok is False
    assert "not a directory" in reason

    # Create directories but empty base_commit
    repo.mkdir()
    wt.mkdir()
    ok, reason = worktrees.worktree_is_clean_ancestor(repo, wt, "")
    assert ok is False
    assert "base_commit must be a non-empty commit hash" in reason

    ok, reason = worktrees.worktree_is_clean_ancestor(repo, wt, "   ")
    assert ok is False
    assert "base_commit must be a non-empty commit hash" in reason
