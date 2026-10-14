from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from local_ai_hub.command_transactions import (
    TransactionStashHook,
    stash_transaction_guard,
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
    _git(path, "config", "user.name", "Test Agent")
    _git(path, "config", "user.email", "agent@example.invalid")
    _git(path, "config", "commit.gpgsign", "false")
    (path / "file1.txt").write_text("initial content\n", encoding="utf-8")
    _git(path, "add", "file1.txt")
    _git(path, "commit", "-m", "initial commit")
    return path


def test_stash_hook_saves_dirty_working_tree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    (repo / "file1.txt").write_text("modified content\n", encoding="utf-8")
    (repo / "new_file.txt").write_text("untracked\n", encoding="utf-8")

    status_before = _git(repo, "status", "--porcelain")
    assert status_before != ""

    hook = TransactionStashHook(repo, message="test stash save")
    saved = hook.save()

    assert saved is True
    assert hook.is_stashed is True
    status_after = _git(repo, "status", "--porcelain")
    assert status_after == ""


def test_stash_hook_noop_on_clean_working_tree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    status_before = _git(repo, "status", "--porcelain")
    assert status_before == ""

    hook = TransactionStashHook(repo)
    saved = hook.save()

    assert saved is False
    assert hook.is_stashed is False
    assert hook.restore() is False
    assert hook.drop() is False
    assert hook.abort() is False


def test_stash_hook_abort_restores_stashed_changes(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    (repo / "file1.txt").write_text("dirty tracked\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("dirty untracked\n", encoding="utf-8")

    hook = TransactionStashHook(repo, message="stash to abort")
    assert hook.save() is True
    assert _git(repo, "status", "--porcelain") == ""

    # Abort transaction -> stashed changes restored
    assert hook.abort() is True
    assert hook.is_stashed is False

    assert (repo / "file1.txt").read_text(encoding="utf-8") == "dirty tracked\n"
    assert (repo / "untracked.txt").read_text(encoding="utf-8") == "dirty untracked\n"


def test_stash_hook_drop_drops_stash_on_success(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    (repo / "file1.txt").write_text("dirty tracked\n", encoding="utf-8")

    hook = TransactionStashHook(repo)
    assert hook.save() is True
    assert _git(repo, "status", "--porcelain") == ""

    # Transaction succeeds -> drop stash
    assert hook.drop() is True
    assert hook.is_stashed is False

    # Tree is at initial commit, stash list is empty
    assert (repo / "file1.txt").read_text(encoding="utf-8") == "initial content\n"
    stashes = _git(repo, "stash", "list")
    assert stashes == ""


def test_stash_transaction_guard_auto_restores_on_exception(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    (repo / "file1.txt").write_text("dirty before transaction\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="simulated failure"):
        with stash_transaction_guard(repo, message="guard stash") as hook:
            assert hook.is_stashed is True
            assert (repo / "file1.txt").read_text(encoding="utf-8") == "initial content\n"
            raise RuntimeError("simulated failure")

    # Stash automatically restored on abort/exception
    assert (repo / "file1.txt").read_text(encoding="utf-8") == "dirty before transaction\n"


def test_stash_transaction_guard_success_with_drop(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    (repo / "file1.txt").write_text("unwanted dirty\n", encoding="utf-8")

    with stash_transaction_guard(repo) as hook:
        assert hook.is_stashed is True
        # Transaction commits new work and drops old stash
        hook.drop()

    assert (repo / "file1.txt").read_text(encoding="utf-8") == "initial content\n"
    assert _git(repo, "stash", "list") == ""
