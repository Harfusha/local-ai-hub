"""Ownership written by worktree creation must be readable by the broker."""

import subprocess

from local_ai_hub import process_utils


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True,
        capture_output=True, text=True, timeout=10,
    )


def test_created_worktree_owner_roundtrips_without_legacy_marker(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Ownership test")
    _git(repo, "config", "user.email", "ownership@example.invalid")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "seed.txt")
    _git(repo, "commit", "-qm", "seed")
    target = tmp_path / "private-worktree"
    created = process_utils.create_git_worktree(
        repo, branch_name="codex/ownership-test", worktree_path=target,
        task_id="owner-task", owner="owner-agent",
    )
    assert created["success"] is True, created
    try:
        admin = process_utils._git_worktree_admin_dir(repo, target)
        assert admin is not None
        assert not (admin / "local_ai_hub_worktree.json").exists()
        ownership = process_utils.get_git_worktree_ownership(repo, target)
    finally:
        removed = process_utils.remove_git_worktree(
            repo, target, branch_name="codex/ownership-test",
            worktree_id=created["worktree_id"],
            expected_task_id="owner-task", expected_owner="owner-agent",
        )
        assert removed["success"] is True, removed
    assert ownership is not None
    assert ownership["task_id"] == "owner-task"
    assert ownership["owner"] == "owner-agent"
    assert ownership["worktree_id"] == created["worktree_id"]
    assert not target.exists()
