from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

from local_ai_hub.change_commit_execution import execute_staged_commit


def _git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root).strip().decode()


def _fixture(root: Path):
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "a").write_text("old")
    (root / "b").write_text("old")
    _git(root, "add", "a", "b")
    _git(root, "commit", "-m", "base")
    (root / "a").write_text("new")
    _git(root, "add", "a")
    (root / "b").write_text("unrelated")
    parent = _git(root, "rev-parse", "HEAD")
    tree = _git(root, "write-tree")
    engine = MagicMock()
    engine.split_changes.return_value = {
        "success": True, "observed_change_set_id": "a" * 64, "git_visible_observation_complete": True,
        "comparison": None, "git_snapshot_metadata": {"head": parent, "index_tree_oid": tree},
        "clusters": [{"group_key": "a", "files": ["a"], "changes": [{"path": "a", "status": "M "}]},
                     {"group_key": "b", "files": ["b"], "changes": [{"path": "b", "status": " M"}]}],
    }
    leases = MagicMock()
    leases.claim.return_value = {"success": True, "lease_id": "lease"}
    leases.renew.return_value = {"success": True}
    leases.release.return_value = {"success": True}
    return engine, leases, parent, tree


def test_commit_staged_only_and_preserve_unrelated_worktree(tmp_path):
    engine, leases, parent, tree = _fixture(tmp_path)
    before = (tmp_path / ".git" / "index").read_bytes()
    result = execute_staged_commit({}, engine, leases, root=str(tmp_path.resolve()), paths=["a"],
                                   expected_revision="a" * 64, expected_tree=tree,
                                   message="chore: reviewed", approved=True)
    assert result["success"], result
    assert _git(tmp_path, "rev-parse", "HEAD^") == parent
    assert _git(tmp_path, "rev-parse", "HEAD^{tree}") == tree
    assert (tmp_path / ".git" / "index").read_bytes() == before
    assert (tmp_path / "b").read_text() == "unrelated"
    assert _git(tmp_path, "show", "HEAD:b") == "old"
    assert not (tmp_path / ".git" / "index.lock").exists()


def test_commit_refuses_hook_and_existing_index_lock(tmp_path):
    engine, leases, parent, tree = _fixture(tmp_path)
    hook = tmp_path / ".git" / "hooks" / "pre-commit"
    hook.write_text("exit 1")
    kwargs = dict(root=str(tmp_path.resolve()), paths=["a"], expected_revision="a" * 64,
                  expected_tree=tree, message="chore: reviewed", approved=True)
    assert not execute_staged_commit({}, engine, leases, **kwargs)["success"]
    hook.unlink()
    lock = tmp_path / ".git" / "index.lock"
    lock.write_text("foreign")
    assert not execute_staged_commit({}, engine, leases, **kwargs)["success"]
    assert lock.read_text() == "foreign"
    lock.unlink()
    assert _git(tmp_path, "rev-parse", "HEAD") == parent


def test_independent_tree_diff_rejects_misreported_selection(tmp_path):
    engine, leases, parent, tree = _fixture(tmp_path)
    plan = engine.split_changes.return_value
    plan["clusters"] = [{"group_key": "b", "files": ["b"], "changes": [{"path": "b", "status": "M "}]}]
    result = execute_staged_commit({}, engine, leases, root=str(tmp_path.resolve()), paths=["b"],
                                   expected_revision="a" * 64, expected_tree=tree,
                                   message="chore: reviewed", approved=True)
    assert not result["success"]
    assert "tree diff" in result["error"]
    assert _git(tmp_path, "rev-parse", "HEAD") == parent


def test_persistent_commit_journal_and_scope(tmp_path):
    from local_ai_hub.change_commit_journal import CommitJournal

    repo = tmp_path / "repo"
    repo.mkdir()
    engine, leases, parent, tree = _fixture(repo)
    journal = CommitJournal(tmp_path / "state")
    result = execute_staged_commit({}, engine, leases, root=str(repo.resolve()), paths=["a"],
                                   expected_revision="a" * 64, expected_tree=tree,
                                   message="chore: reviewed", approved=True, journal=journal)
    assert result["success"], result
    reopened = CommitJournal(tmp_path / "state")
    observed = reopened.inspect(str(repo.resolve()), result["operation_id"])
    assert observed["state"] == "published"
    assert observed["recovery_status"] == "candidate_is_branch_tip"
    assert observed["retry_authorized"] is False
    assert not reopened.inspect(str(tmp_path), result["operation_id"])["success"]


def test_journal_failure_before_cas_is_non_mutating(tmp_path):
    engine, leases, parent, tree = _fixture(tmp_path)
    journal = MagicMock()
    journal.prepare.side_effect = OSError("storage unavailable")
    result = execute_staged_commit({}, engine, leases, root=str(tmp_path.resolve()), paths=["a"],
                                   expected_revision="a" * 64, expected_tree=tree,
                                   message="chore: reviewed", approved=True, journal=journal)
    assert not result["success"]
    assert not result["outcome_unknown"]
    assert _git(tmp_path, "rev-parse", "HEAD") == parent


def test_explicit_mixed_scope_commit_preserves_unstaged_hunks(tmp_path):
    engine, leases, parent, tree = _fixture(tmp_path)
    (tmp_path / "a").write_text("additional unstaged content")
    engine.split_changes.return_value["clusters"][0]["changes"][0]["status"] = "MM"
    kwargs = dict(root=str(tmp_path.resolve()), paths=["a"], expected_revision="a" * 64,
                  expected_tree=tree, message="chore: reviewed", approved=True)
    assert not execute_staged_commit({}, engine, leases, **kwargs)["success"]
    result = execute_staged_commit({}, engine, leases, **kwargs, allow_mixed_staged=True)
    assert result["success"], result
    assert _git(tmp_path, "show", "HEAD:a") == "new"
    assert (tmp_path / "a").read_text() == "additional unstaged content"


def test_sequence_preview_and_publish_two_commits_atomically(tmp_path):
    engine, leases, parent, _ = _fixture(tmp_path)
    _git(tmp_path, "add", "b")
    tree = _git(tmp_path, "write-tree")
    plan = engine.split_changes.return_value
    plan["git_snapshot_metadata"]["index_tree_oid"] = tree
    plan["clusters"][1]["changes"][0]["status"] = "M "
    sequence = [{"paths": ["a"], "message": "chore: a"}, {"paths": ["b"], "message": "chore: b"}]
    kwargs = dict(root=str(tmp_path.resolve()), paths=["a", "b"], expected_revision="a" * 64,
                  expected_tree=tree, message="", sequence=sequence)
    preview = execute_staged_commit({}, engine, leases, **kwargs, approved=False, preview_only=True)
    assert preview["success"], preview
    assert _git(tmp_path, "rev-parse", "HEAD") == parent
    assert not execute_staged_commit({}, engine, leases, **kwargs, approved=True, preview_digest="wrong")["success"]
    result = execute_staged_commit({}, engine, leases, **kwargs, approved=True, preview_digest=preview["preview_digest"])
    assert result["success"], result
    assert len(result["commit_oids"]) == 2
    assert _git(tmp_path, "rev-parse", "HEAD^^") == parent
    assert _git(tmp_path, "show", "HEAD^:b") == "old"
    assert _git(tmp_path, "show", "HEAD:b") == "unrelated"
    assert _git(tmp_path, "rev-parse", "HEAD^{tree}") == tree
