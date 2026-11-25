from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from local_ai_hub.repo_knowledge_sync import checkout_sync_status


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, timeout=10).stdout


@pytest.mark.skipif(shutil.which("git") is None, reason="Git unavailable")
def test_checkout_status_distinguishes_shared_changes_and_private_state(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "Fixture")
    _git(root, "config", "user.email", "fixture@example.invalid")
    hub = root / ".local-ai-hub"
    hub.mkdir()
    (hub / ".gitignore").write_text("local/\n", encoding="utf-8")
    (hub / "project.json").write_text("{}", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "initial")
    assert checkout_sync_status(root)["state"] == "clean_shared_paths"
    (hub / "local").mkdir()
    (hub / "local/private.json").write_text("private", encoding="utf-8")
    assert checkout_sync_status(root)["state"] == "clean_shared_paths"
    (hub / "knowledge").mkdir()
    (hub / "knowledge/rule.json").write_text("{}", encoding="utf-8")
    result = checkout_sync_status(root)
    assert result["state"] == "local_changes"
    assert result["entries"] == [{"path": ".local-ai-hub/knowledge/rule.json",
                                  "index_worktree_status": "??", "state": "untracked"}]
    assert not result["remote_verified"]
    _git(root, "add", "-f", ".local-ai-hub/local/private.json")
    result = checkout_sync_status(root)
    assert result["tracked_local_state"]
    assert result["state"] == "unsafe_local_tracking"
    assert "private.json" not in str(result)


def test_non_checkout_does_not_claim_sync(tmp_path):
    assert checkout_sync_status(tmp_path) == {"state": "not_git_checkout", "complete": False}


@pytest.mark.skipif(shutil.which("git") is None, reason="Git unavailable")
@pytest.mark.parametrize("divergent", [False, True])
def test_two_clone_semantic_conflict_is_read_only(tmp_path, divergent):
    root = tmp_path / "first"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "Fixture")
    _git(root, "config", "user.email", "fixture@example.invalid")
    relative = ".local-ai-hub/knowledge/rules/rule.json"
    path = root / relative
    path.parent.mkdir(parents=True)
    record = {
        "schema_version": 1, "project_id": "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb",
        "kind": "business_rule", "id": "rule",
        "payload": {"title": "Rule", "statement": "Initial intent", "layer": "intended"},
        "provenance": {"origin_kind": "manual"}, "evidence": [], "relations": [],
    }

    def write(target, **changes):
        # One line forces Git to surface the textual conflict even for
        # independent semantic groups.
        target.write_text(json.dumps({**record, "payload": {**record["payload"], **changes}}) + "\n",
                          encoding="utf-8")

    write(path)
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")
    second = tmp_path / "second"
    _git(root, "clone", str(root), str(second))
    _git(second, "config", "user.name", "Fixture")
    _git(second, "config", "user.email", "fixture@example.invalid")
    write(path, statement="First developer intent")
    _git(root, "commit", "-am", "first change")
    write(second / relative, **({"statement": "Second developer intent"} if divergent else {"title": "New title"}))
    _git(second, "commit", "-am", "second change")
    _git(second, "fetch", "origin")
    merge = subprocess.run(["git", "-C", str(second), "merge", "origin/main"], capture_output=True, timeout=10)
    assert merge.returncode == 1
    before = (second / relative).read_bytes()
    stages = _git(second, "ls-files", "-u", "-z")
    result = checkout_sync_status(second)
    assert result["state"] == "conflict"
    summary = result["conflicts"][0]
    assert summary["path"] == relative
    assert summary["classification"] == (
        "divergent_semantic_edit" if divergent else "nondivergent_edit_candidate"
    )
    assert summary["conflicting_groups"] == (["declaration"] if divergent else [])
    assert summary["requires_review"] is True
    assert "developer intent" not in str(result)
    assert (second / relative).read_bytes() == before
    assert _git(second, "ls-files", "-u", "-z") == stages


@pytest.mark.skipif(shutil.which("git") is None, reason="Git unavailable")
def test_committed_knowledge_diff_is_scoped_and_does_not_claim_runtime_verification(tmp_path):
    from local_ai_hub.repo_knowledge_sync import compare_knowledge_revisions

    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "Fixture")
    _git(root, "config", "user.email", "fixture@example.invalid")
    project = "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb"
    hub = root / ".local-ai-hub"
    rules = hub / "knowledge/rules"
    rules.mkdir(parents=True)
    (hub / "project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": project, "mode": "shared",
    }), encoding="utf-8")

    def write_rule(identifier, statement):
        record = {
            "schema_version": 1, "project_id": project,
            "kind": "business_rule", "id": identifier,
            "payload": {"title": identifier, "statement": statement, "layer": "intended"},
            "provenance": {"origin_kind": "manual"}, "evidence": [], "relations": [],
        }
        (rules / (identifier + ".json")).write_text(json.dumps(record), encoding="utf-8")

    write_rule("modify", "Original statement")
    write_rule("remove", "To be removed")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")
    base = _git(root, "rev-parse", "HEAD").decode().strip()
    write_rule("modify", "Changed confidential statement")
    write_rule("add", "New statement")
    (rules / "remove.json").unlink()
    _git(root, "add", ".")
    _git(root, "commit", "-m", "change")
    # Dirty state must not be confused with the selected Git commit.
    write_rule("modify", "Uncommitted edit")
    before = _git(root, "status", "--porcelain")
    result = compare_knowledge_revisions(root, base)
    assert result["complete"]
    assert result["committed_only"] and not result["runtime_verified"]
    assert {row["id"]: row["state"] for row in result["changes"]} == {
        "add": "added", "modify": "modified", "remove": "removed",
    }
    changed = next(row for row in result["changes"] if row["id"] == "modify")
    assert changed["changed_groups"] == ["payload"]
    assert changed["previous_layer"] == changed["current_layer"] == "intended"
    assert "confidential statement" not in str(result)
    assert before == _git(root, "status", "--porcelain")
    assert compare_knowledge_revisions(root, "--help")["state"] == "revision_unavailable"
    assert compare_knowledge_revisions(root, "HEAD")["changes"] == []
