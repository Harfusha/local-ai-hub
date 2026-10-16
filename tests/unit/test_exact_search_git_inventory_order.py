"""Deferred source regressions for mixed tracked/untracked Git inventories."""
import io

import pytest

from local_ai_hub import repo_tools
from local_ai_hub.repo_tools import RepositoryTools


class _Process:
    pid = 12345

    def __init__(self, payload):
        self.stdout = io.BytesIO(payload)

    def poll(self):
        return 0

    def wait(self, timeout=None):
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
