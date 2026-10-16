from pathlib import Path
import pytest

from local_ai_hub.worktrees import (
    is_valid_worktree_name,
    is_hub_temporary_worktree,
    is_git_worktree,
    discover_worktree_roots,
)


def test_is_valid_worktree_name_hardening():
    assert is_valid_worktree_name("wt-valid-123") is True
    assert is_valid_worktree_name("feature/branch-1") is True

    # Rejection of invalid trailing chars or types
    assert is_valid_worktree_name("wt\\") is False
    assert is_valid_worktree_name("wt.") is False
    assert is_valid_worktree_name("wt/") is False
    assert is_valid_worktree_name(True) is False
    assert is_valid_worktree_name(None) is False
    assert is_valid_worktree_name("bad\x00name") is False
    assert is_valid_worktree_name("-starts-with-dash") is False


def test_is_hub_temporary_worktree_hardening():
    assert is_hub_temporary_worktree(True) is False
    assert is_hub_temporary_worktree(False) is False
    assert is_hub_temporary_worktree(None) is False
    assert is_hub_temporary_worktree("bad\x00path") is False
    assert is_hub_temporary_worktree("") is False


def test_is_git_worktree_hardening():
    assert is_git_worktree(True) is False
    assert is_git_worktree(False) is False
    assert is_git_worktree(None) is False
    assert is_git_worktree("bad\x00path") is False
    assert is_git_worktree("") is False


def test_discover_worktree_roots_hardening():
    assert discover_worktree_roots(True) == []
    assert discover_worktree_roots(False) == []
    assert discover_worktree_roots(None) == []
    assert discover_worktree_roots("bad\x00path") == []
    assert discover_worktree_roots("") == []
