from __future__ import annotations

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
