"""Deferred source regressions for mixed tracked/untracked Git inventories."""
import io
from types import SimpleNamespace

import pytest

from local_ai_hub import repo_tools
from local_ai_hub.repo_tools import RepositoryTools


class _Process:
    pid = 12345

    def __init__(self, payload):
        self.stdout = io.BytesIO(payload)

    def poll(self):
        return 0

    def wait(self, *, timeout):
        assert 0 < timeout <= 60
        return 0


def _search(tmp_path, monkeypatch, payload):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(repo_tools, "popen_managed", lambda *args, **kwargs: _Process(payload))
    tools = RepositoryTools({"rag": {"extensions": [".py"]}, "search": {"use_ripgrep_if_available": False}})
    return tools.search(str(tmp_path), "audit_needle", exact_count=True, limit=10)


def test_combined_git_groups_are_sorted_and_deduplicated(tmp_path, monkeypatch):
    for name in ["z_tracked.py", "a_untracked.py", "ž_unicode.py"]:
        (tmp_path / name).write_text("audit_needle = 1\n", encoding="utf-8")
    payload = "z_tracked.py\0a_untracked.py\0ž_unicode.py\0z_tracked.py\0".encode("utf-8")
    result = _search(tmp_path, monkeypatch, payload)
    assert result["success"] is True, result
    assert result["count_exact"] is True
    assert result["total_matches"] == 3
    assert result["scanned_files"] == 3
    assert len(result["results"]) == 3


@pytest.mark.parametrize("bound", ["MAX_EXACT_GIT_PATHS", "MAX_EXACT_GIT_PATH_BYTES"])
def test_inventory_bounds_fail_without_partial_success(tmp_path, monkeypatch, bound):
    monkeypatch.setattr(repo_tools, bound, 1)
    result = _search(tmp_path, monkeypatch, b"one.py\0two.py\0")
    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert result["results"] == []


def test_invalid_wait_protocol_does_not_retry_without_timeout(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    process = _Process(b"one.py\0")
    calls = []

    def invalid_wait(**kwargs):
        calls.append(kwargs)
        raise TypeError("invalid wait protocol")

    process.wait = invalid_wait
    monkeypatch.setattr(repo_tools, "popen_managed", lambda *args, **kwargs: process)
    tools = RepositoryTools({"rag": {"extensions": [".py"]}, "search": {"use_ripgrep_if_available": False}})
    with pytest.raises(TypeError, match="invalid wait protocol"):
        tools.search(str(tmp_path), "audit_needle", exact_count=True, limit=10)
    assert len(calls) == 1
    assert set(calls[0]) == {"timeout"}
    assert 0 < calls[0]["timeout"] <= 60
    assert process.stdout.closed


def test_exact_search_prefilters_ignored_dirs_and_preserves_forced_paths(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".venv").mkdir()
    (tmp_path / "state").mkdir()
    (tmp_path / "match.py").write_text("audit_needle = 1\n", encoding="utf-8")
    (tmp_path / "skip.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / ".venv" / "forced.py").write_text("audit_needle = 2\n", encoding="utf-8")
    (tmp_path / "state" / "cache.py").write_text("audit_needle = 3\n", encoding="utf-8")
    payload = b"match.py\0skip.py\0.venv/forced.py\0state/cache.py\0"
    monkeypatch.setattr(repo_tools, "popen_managed", lambda *args, **kwargs: _Process(payload))

    rg_calls = []

    def fake_ripgrep(command, **_kwargs):
        rg_calls.append(command)
        return SimpleNamespace(returncode=0, stdout="match.py\n", stderr="")

    monkeypatch.setattr(repo_tools.subprocess, "run", fake_ripgrep)
    tools = RepositoryTools({
        "rag": {"extensions": [".py"]},
        "server": {"state_dir": str(tmp_path / "state")},
    })
    tools._rg = "rg"
    tools._project_file_allowed = lambda *_args, **_kwargs: True
    tools._path_extension_is_searchable = lambda *_args, **_kwargs: True

    result = tools.search(
        str(tmp_path), "audit_needle", limit=10, exact_count=True,
        project_settings=object(), force_include_paths=[".venv/forced.py"],
    )

    assert "!**/.venv/**" in rg_calls[0]
    assert "!state/**" in rg_calls[0]
    assert result["success"] is True, result
    assert result["count_exact"] is True
    assert result["total_matches"] == 2
    assert result["scanned_files"] == 2
    assert {item["path"] for item in result["results"]} == {"match.py", ".venv/forced.py"}
