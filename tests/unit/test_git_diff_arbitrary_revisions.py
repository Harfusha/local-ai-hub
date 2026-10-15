"""Deferred bundle regressions; Git writes are confined to tmp_path."""
import subprocess
from types import SimpleNamespace

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.process_utils import hidden_run_kwargs
from local_ai_hub.repo_tools import RepositoryTools


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=True, timeout=5, **hidden_run_kwargs()).stdout.strip()


def test_revision_pair_uses_merge_base_and_excludes_dirty_files(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Bundle Test")
    target = root / "beta.py"
    target.write_text("value = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")
    base = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "-b", "left")
    (root / "left.py").write_text("left = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "left")
    left = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "-b", "right", base)
    target.write_text("value = 2\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "right")
    right = _git(root, "rev-parse", "HEAD")
    (root / "dirty.py").write_text("dirty = 1\n", encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    tools = RepositoryTools(config)
    result = tools.git_diff(str(root), rev1="left", rev2="right")
    assert result["success"], result
    assert result["comparison"] == "merge_base"
    assert result["resolved_rev1"] == left
    assert result["resolved_rev2"] == right
    assert result["changed_files"] == ["beta.py"]
    assert result["changed_paths"] == ["beta.py"]
    assert "left.py" not in result["diff"]
    engine = DeterministicEngine(config, tools)
    try:
        structured = engine.git_diff(str(root), rev1=base, rev2=right, path="beta.py")
        assert structured["success"], structured
        assert structured["files"][0]["file"] == "beta.py"
        assert structured["stats_complete"] is True
    finally:
        observer = getattr(engine, "_cache_observer", None)
        if observer is not None:
            observer.close()


@pytest.mark.parametrize("kwargs", [
    {"rev1": "HEAD"}, {"rev1": "HEAD", "rev2": "HEAD", "staged": True},
    {"rev1": "--output=foreign", "rev2": "HEAD"},
])
def test_invalid_revision_options_are_rejected(tmp_path, kwargs):
    result = RepositoryTools({}).git_diff(str(tmp_path), **kwargs)
    assert result["success"] is False


def test_mcp_revision_arguments_reach_existing_route(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mcp_server.FEATURES, "repo", True)
    monkeypatch.setattr(mcp_server, "CLIENT", SimpleNamespace(post=lambda path, payload, **_kwargs:
                        calls.append((path, payload)) or {"success": True, "comparison": "merge_base"}))
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_kwargs: None)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)
    result = mcp_server.local_ai_repo(action="git_diff", root=str(tmp_path), rev1="HEAD~3", rev2="HEAD")
    assert result["success"], result
    assert calls[0][0] == "/api/git/diff"
    assert calls[0][1]["rev1"] == "HEAD~3"
    assert calls[0][1]["rev2"] == "HEAD"
