from __future__ import annotations

from pathlib import Path

from local_ai_hub import process_utils
from local_ai_hub.repo_tools import RepositoryTools


def _git(path: Path, *args: str) -> str:
    result = process_utils.run_hidden(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout.strip()


def test_git_worktree_pointer_is_supported_by_repository_tools(tmp_path):
    repo = tmp_path / "repository"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.name", "Local AI Hub tests")
    _git(repo, "config", "user.email", "tests@example.invalid")
    (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "--quiet", "-m", "initial")

    worktree = tmp_path / "worktree"
    _git(repo, "worktree", "add", "--quiet", "--detach", str(worktree), "HEAD")

    assert (worktree / ".git").is_file()
    inventory = RepositoryTools({})._git_files(worktree)
    assert inventory is not None
    assert (worktree / "tracked.txt").resolve() in inventory

    expected_git_dir = Path(_git(worktree, "rev-parse", "--absolute-git-dir"))
    ownership_path = process_utils._worktree_ownership_path(worktree)
    assert ownership_path == expected_git_dir / process_utils._WORKTREE_OWNERSHIP_FILE
