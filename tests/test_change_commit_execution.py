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


def test_exact_tree_receipts_bind_sequence_and_environment(tmp_path):
    import sys
    from local_ai_hub.change_commit_journal import CommitJournal
    from local_ai_hub.change_tree_verification import verify_sequence

    repo = tmp_path / "repo"
    repo.mkdir()
    engine, leases, parent, _ = _fixture(repo)
    _git(repo, "add", "b")
    tree = _git(repo, "write-tree")
    plan = engine.split_changes.return_value
    plan["git_snapshot_metadata"]["index_tree_oid"] = tree
    plan["clusters"][1]["changes"][0]["status"] = "M "
    sequence = [{"paths": ["a"], "message": "chore: a"}, {"paths": ["b"], "message": "chore: b"}]
    journal = CommitJournal(tmp_path / "state")
    kwargs = dict(root=str(repo.resolve()), paths=["a", "b"], expected_revision="a" * 64,
                  expected_tree=tree, message="", sequence=sequence, journal=journal)
    preview = execute_staged_commit({}, engine, leases, **kwargs, approved=False, preview_only=True)
    assert preview["success"], preview
    manifest = {"environment_id": "c" * 64, "commands": [[sys.executable, "-c",
                "from pathlib import Path; assert Path('a').read_text() == 'new'; assert not Path('.git').exists()"]]}
    result = verify_sequence(str(repo.resolve()), preview, manifest, journal)
    assert result["success"], result
    assert len(result["verified_steps"]) == 2
    assert result["executed_step_count"] == 2
    reused = verify_sequence(str(repo.resolve()), preview, manifest, journal)
    assert reused["success"], reused
    assert reused["reused_step_count"] == 2
    assert reused["executed_step_count"] == 0
    assert [s["receipt_id"] for s in reused["verified_steps"]] == [
        s["receipt_id"] for s in result["verified_steps"]
    ]
    refreshed = verify_sequence(str(repo.resolve()), preview, manifest, journal, rerun=True)
    assert refreshed["success"], refreshed
    assert refreshed["executed_step_count"] == 2
    assert [s["receipt_id"] for s in refreshed["verified_steps"]] != [
        s["receipt_id"] for s in result["verified_steps"]
    ]
    denied = execute_staged_commit({}, engine, leases, **kwargs, approved=True,
                                  preview_digest=preview["preview_digest"],
                                  verification_manifest={**manifest, "environment_id": "d" * 64})
    assert not denied["success"]
    applied = execute_staged_commit({}, engine, leases, **kwargs, approved=True,
                                   preview_digest=preview["preview_digest"], verification_manifest=manifest)
    assert applied["success"], applied
    assert len(applied["tree_check_receipt_ids"]) == 2


def test_new_verification_attempt_revokes_old_success(tmp_path):
    import pytest
    from local_ai_hub.change_commit_journal import CommitJournal

    journal = CommitJournal(tmp_path / "state")
    scope = dict(root=str(tmp_path), tree="1" * 40, command_id="2" * 64, environment_id="3" * 64)
    checks = [{"exit_code": 0, "output_complete": True}]
    attempt = journal.begin_tree_checks(**scope)
    receipt = journal.record_tree_checks(**scope, checks=checks, ttl=60, attempt=attempt)
    assert journal.current_tree_checks(**scope) == receipt
    newer = journal.begin_tree_checks(**scope)
    assert journal.current_tree_checks(**scope) is None
    with pytest.raises(ValueError, match="superseded"):
        journal.record_tree_checks(**scope, checks=checks, ttl=60, attempt=attempt)
    assert journal.record_tree_checks(**scope, checks=checks, ttl=60, attempt=newer)


def test_commit_list_is_root_scoped(tmp_path):
    from local_ai_hub.change_commit_journal import CommitJournal

    journal = CommitJournal(tmp_path / "state")
    journal.prepare(operation_id="1" * 32, root=str(tmp_path), branch="refs/heads/main",
                    parent="2" * 40, tree="3" * 40, candidate="4" * 40)
    assert len(journal.list_recent(str(tmp_path))["operations"]) == 1
    assert not journal.list_recent(str(tmp_path / "other"))["operations"]


def test_shared_project_commit_policy_requires_exact_manifest_and_receipts(tmp_path):
    import json
    import sys

    import pytest

    from local_ai_hub.change_tree_verification import commit_policy

    engine, leases, parent, tree = _fixture(tmp_path)
    executable = str(Path(sys.executable).absolute())
    argv = [executable, "-c", "print('verified')"]
    (tmp_path / ".local-ai.toml").write_text(
        "[commands.check]\nargv = " + json.dumps(argv) +
        "\n[verification_rules]\ngit_commit = [\"check\"]\n", encoding="utf-8",
    )
    root = str(tmp_path.resolve())
    policy = commit_policy(root)
    assert policy["required"] is True
    assert policy["command_aliases"] == ["check"]
    manifest = {"environment_id": "b" * 64, "commands": [argv]}
    assert commit_policy(root, manifest, require_manifest=True) == policy
    with pytest.raises(ValueError, match="exactly match"):
        commit_policy(root, {**manifest, "commands": [[executable, "-V"]]}, require_manifest=True)
    kwargs = dict(root=root, paths=["a"], expected_revision="a" * 64, expected_tree=tree,
                  message="fix: reviewed", approved=True)
    refused = execute_staged_commit({}, engine, leases, **kwargs)
    assert not refused["success"] and "git_commit policy" in refused["error"]
    sequence = [{"paths": ["a"], "message": "fix: reviewed"}]
    preview = execute_staged_commit({}, engine, leases, **kwargs, sequence=sequence, preview_only=True)
    assert preview["success"], preview
    assert preview["project_commit_policy"] == policy
    refused = execute_staged_commit({}, engine, leases, **kwargs, sequence=sequence,
                                   preview_digest=preview["preview_digest"])
    assert not refused["success"]
    assert _git(tmp_path, "rev-parse", "HEAD") == parent


def test_historical_context_benchmark_measures_real_commit_without_mutation(tmp_path):
    from tools.benchmark_git_change_context import measure_history

    _fixture(tmp_path)
    _git(tmp_path, "commit", "-m", "change a")
    head = _git(tmp_path, "rev-parse", "HEAD")
    index = (tmp_path / ".git" / "index").read_bytes()
    before = (tmp_path / "b").read_bytes()
    result = measure_history(tmp_path, "HEAD~1", "HEAD")
    assert result["workload"] == "real_committed_range"
    assert result["inventory"]["changed_paths"] == 1
    assert result["inventory"]["observed_paths"] == 1
    assert result["inventory"]["explicitly_listed_paths"] == 1
    assert result["inventory"]["patch_coverage_complete"]
    assert result["estimated_tokens"]["raw"] > 0
    assert result["estimated_tokens"]["compact_all_pages"] > 0
    assert _git(tmp_path, "rev-parse", "HEAD") == head
    assert (tmp_path / ".git" / "index").read_bytes() == index
    assert (tmp_path / "b").read_bytes() == before


def test_sequence_suggestion_is_editable_and_requires_exact_preview(tmp_path):
    from local_ai_hub.change_commit_sequence import suggest_sequence

    engine, leases, parent, tree = _fixture(tmp_path)
    plan = engine.split_changes.return_value
    plan["inventory_scope"] = "git_visible_changes"
    plan["dependency_plan"] = {"candidate_commit_units": [["a"], ["b"]]}
    plan["clusters"][0]["suggested_commit_message"] = "fix: a"
    proposal = suggest_sequence(plan, "a" * 64)
    assert proposal["success"], proposal
    assert proposal["selected_paths"] == ["a"]
    assert proposal["sequence"] == [{"paths": ["a"], "message": "fix: a"}]
    assert proposal["tree_oid"] == tree
    assert proposal["requires_sequence_preview"] and not proposal["commit_ready"]
    assert "preview_digest" not in proposal
    assert _git(tmp_path, "rev-parse", "HEAD") == parent
    preview = execute_staged_commit({}, engine, leases, root=str(tmp_path.resolve()),
                                    paths=proposal["selected_paths"], expected_revision=proposal["observed_change_set_id"],
                                    expected_tree=tree, message="", approved=False,
                                    sequence=proposal["sequence"], preview_only=True)
    assert preview["success"], preview
    assert preview["preview_digest"]
    assert _git(tmp_path, "rev-parse", "HEAD") == parent
    assert not suggest_sequence(plan, "b" * 64)["success"]
    plan["clusters"][0]["dependency_group_candidates"] = ["b"]
    blocked = suggest_sequence(plan)
    assert not blocked["success"]
    assert "unselected_dependency_candidates" in blocked["blockers"]
