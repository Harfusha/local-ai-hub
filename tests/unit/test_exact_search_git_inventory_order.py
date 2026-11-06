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
    (tmp_path / "match.py").write_text("safe_needle = 1\n", encoding="utf-8")
    (tmp_path / "skip.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / ".venv" / "forced.py").write_text("safe_needle = 2\n", encoding="utf-8")
    (tmp_path / "state" / "cache.py").write_text("safe_needle = 3\n", encoding="utf-8")
    payload = b"match.py\0skip.py\0.venv/forced.py\0state/cache.py\0"
    monkeypatch.setattr(repo_tools, "popen_managed", lambda *args, **kwargs: _Process(payload))

    search_calls = []

    def fake_run(command, **_kwargs):
        if command[0] == "rg":
            search_calls.append(command)
            return SimpleNamespace(returncode=0, stdout="match.py\n", stderr="")
        return SimpleNamespace(returncode=1, stdout=b"", stderr=b"")

    monkeypatch.setattr(repo_tools.subprocess, "run", fake_run)
    tools = RepositoryTools({
        "rag": {"extensions": [".py"]},
        "server": {"state_dir": str(tmp_path / "state")},
    })
    tools._rg = "rg"
    tools._project_file_allowed = lambda *_args, **_kwargs: True
    tools._path_extension_is_searchable = lambda *_args, **_kwargs: True

    result = tools.search(
        str(tmp_path), "safe_needle", limit=10, exact_count=True,
        project_settings=SimpleNamespace(exclude_paths=["custom/**"]),
        force_include_paths=[".venv/forced.py"],
    )

    assert search_calls
    assert result["success"] is True, result
    assert result["count_exact"] is True
    assert result["total_matches"] == 2
    assert result["scanned_files"] == 2
    assert {item["path"] for item in result["results"]} == {"match.py", ".venv/forced.py"}


def test_exact_search_computes_path_priority_once_per_matching_file(tmp_path):
    path = tmp_path / "many.py"
    path.write_text("".join(f"needle_{index} = 1\n" for index in range(80)), encoding="utf-8")
    calls = []
    tools = RepositoryTools({"rag": {"extensions": [".py"]}})

    def priority(relative):
        calls.append(relative)
        return (0, 0, 0)

    result = tools.search(str(tmp_path), "needle", limit=10, exact_count=True, path_priority=priority)

    assert result["success"] is True
    assert result["total_matches"] > 1
    assert calls == ["many.py"]


def test_exact_search_uses_complete_ascii_ripgrep_candidates_without_git_inventory(
    tmp_path, monkeypatch,
):
    (tmp_path / "match.py").write_text("safe_needle = 1\n", encoding="utf-8")
    (tmp_path / "other.py").write_text("unrelated = 1\n", encoding="utf-8")
    rg_calls = []

    def fake_ripgrep(command, **_kwargs):
        rg_calls.append(command)
        return SimpleNamespace(returncode=0, stdout="match.py\n", stderr="")

    def unexpected_git_inventory(*_args, **_kwargs):
        raise AssertionError("complete ripgrep candidates should skip Git inventory")

    monkeypatch.setattr(repo_tools.subprocess, "run", fake_ripgrep)
    monkeypatch.setattr(repo_tools, "popen_managed", unexpected_git_inventory)
    tools = RepositoryTools({
        "rag": {"extensions": [".py"]},
        "search": {"use_ripgrep_if_available": True},
    })
    tools._rg = "rg"
    tools._project_file_allowed = lambda *_args, **_kwargs: True
    tools._path_extension_is_searchable = lambda *_args, **_kwargs: True

    result = tools.search(
        str(tmp_path), "safe_needle", limit=10, exact_count=True,
        project_settings=object(),
    )

    assert len(rg_calls) == 1
    assert result["success"] is True, result
    assert result["count_exact"] is True
    assert result["total_matches"] == 1
    assert result["scanned_files"] == 1
    assert [item["path"] for item in result["results"]] == ["match.py"]


def test_git_exact_search_uses_git_grep_candidates_for_tracked_and_untracked(
    tmp_path, monkeypatch,
):
    (tmp_path / ".git").mkdir()
    for name in ("tracked.py", "untracked.py", "ignored.py"):
        (tmp_path / name).write_text("safe_needle = 1\n", encoding="utf-8")
    inventory = b"tracked.py\0untracked.py\0ignored.py\0"
    monkeypatch.setattr(repo_tools, "popen_managed", lambda *args, **kwargs: _Process(inventory))

    grep_calls = []

    def fake_git_grep(command, **_kwargs):
        grep_calls.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout=b"tracked.py\0untracked.py\0",
            stderr=b"",
        )

    monkeypatch.setattr(repo_tools.subprocess, "run", fake_git_grep)
    tools = RepositoryTools({
        "rag": {"extensions": [".py"]},
        "search": {
            "use_ripgrep_if_available": False,
            "use_git_grep_fallback": True,
            "prefer_git": True,
        },
    })
    tools._project_file_allowed = lambda *_args, **_kwargs: True
    tools._path_extension_is_searchable = lambda *_args, **_kwargs: True

    result = tools.search(str(tmp_path), "safe_needle", limit=10, exact_count=True)

    assert result["success"] is True, result
    assert result["count_exact"] is True
    assert result["total_matches"] == 2
    assert {item["path"] for item in result["results"]} == {"tracked.py", "untracked.py"}
    assert grep_calls[0][1:3] == ["-C", str(tmp_path)]
    assert "--untracked" in grep_calls[0]
    assert "--exclude-standard" in grep_calls[0]


def test_complete_git_grep_candidates_skip_full_git_inventory(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    (tmp_path / "match.py").write_text("safe_needle = 1\n", encoding="utf-8")
    grep_calls = []

    def fake_git_grep(command, **_kwargs):
        grep_calls.append(command)
        return SimpleNamespace(returncode=0, stdout=b"match.py\0", stderr=b"")

    def unexpected_inventory(*_args, **_kwargs):
        raise AssertionError("complete git grep candidates should skip full inventory")

    monkeypatch.setattr(repo_tools.subprocess, "run", fake_git_grep)
    monkeypatch.setattr(repo_tools, "popen_managed", unexpected_inventory)
    tools = RepositoryTools({
        "rag": {"extensions": [".py"]},
        "search": {"use_ripgrep_if_available": False, "use_git_grep_fallback": True},
    })
    tools._project_file_allowed = lambda *_args, **_kwargs: True
    tools._path_extension_is_searchable = lambda *_args, **_kwargs: True

    result = tools.search(str(tmp_path), "safe_needle", exact_count=True, limit=10)

    assert len(grep_calls) == 1
    assert result["success"] is True, result
    assert result["count_exact"] is True
    assert result["total_matches"] == 1
    assert result["scanned_files"] == 1
    assert [item["path"] for item in result["results"]] == ["match.py"]


def test_ripgrep_candidates_are_preferred_and_skip_git_inventory_safely(tmp_path, monkeypatch):
    real_run = repo_tools.subprocess.run
    real_run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
    (tmp_path / ".gitignore").write_text(
        "tracked_ignored.py\nignored_untracked.py\n", encoding="utf-8",
    )
    for name in ("match.py", "tracked_ignored.py", "ignored_untracked.py"):
        (tmp_path / name).write_text("safe_needle = 1\n", encoding="utf-8")
    real_run(["git", "add", "-f", "tracked_ignored.py"], cwd=str(tmp_path), check=True)

    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[0] == "rg":
            return SimpleNamespace(
                returncode=0,
                stdout="match.py\ntracked_ignored.py\nignored_untracked.py\n",
                stderr="",
            )
        return real_run(command, **kwargs)

    def unexpected_inventory(*_args, **_kwargs):
        raise AssertionError("complete ripgrep candidates should skip full Git inventory")

    monkeypatch.setattr(repo_tools.subprocess, "run", fake_run)
    monkeypatch.setattr(repo_tools, "popen_managed", unexpected_inventory)
    tools = RepositoryTools({
        "rag": {"extensions": [".py"]},
        "search": {"use_ripgrep_if_available": True, "prefer_git": True},
    })
    tools._rg = "rg"
    tools._project_file_allowed = lambda *_args, **_kwargs: True
    tools._path_extension_is_searchable = lambda *_args, **_kwargs: True

    result = tools.search(str(tmp_path), "safe_needle", exact_count=True, limit=10)

    assert result["success"] is True, result
    assert result["count_exact"] is True
    assert result["total_matches"] == 2
    assert result["scanned_files"] == 2
    assert {item["path"] for item in result["results"]} == {
        "match.py", "tracked_ignored.py",
    }
    assert commands[0][0] == "rg"
    assert commands[1][3] == "check-ignore"


def test_git_grep_exact_search_returns_live_tracked_and_untracked_files(tmp_path):
    def git(*args):
        repo_tools.subprocess.run(
            ["git", *args], cwd=str(tmp_path), check=True,
            capture_output=True, text=True,
        )

    git("init", "-q")
    git("config", "user.email", "search-test@example.invalid")
    git("config", "user.name", "Search Test")
    (tmp_path / "tracked.py").write_text("rare_anchor_token = 1\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (tmp_path / "untracked.py").write_text("rare_anchor_token = 2\n", encoding="utf-8")
    (tmp_path / "ignored.py").write_text("rare_anchor_token = 3\n", encoding="utf-8")
    (tmp_path / "different_case.py").write_text("RARE_ANCHOR_TOKEN = 4\n", encoding="utf-8")
    git("add", "tracked.py", ".gitignore")
    git("commit", "-qm", "tracked source")

    tools = RepositoryTools({"rag": {"extensions": [".py"]}})
    result = tools.search(str(tmp_path), "rare_anchor_token", limit=10, exact_count=True)

    assert result["success"] is True, result
    assert result["count_exact"] is True
    assert result["total_matches"] == 2
    assert {item["path"] for item in result["results"]} == {"tracked.py", "untracked.py"}


def test_exact_search_does_not_narrow_ripgrep_for_more_than_sixteen_terms(
    tmp_path, monkeypatch,
):
    (tmp_path / ".git").mkdir()
    (tmp_path / "match.py").write_text("term16 = 1\n", encoding="utf-8")
    git_calls = []
    rg_calls = []

    def fake_git(*_args, **_kwargs):
        git_calls.append(True)
        return _Process(b"match.py\0")

    def incomplete_ripgrep(*_args, **_kwargs):
        rg_calls.append(True)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(repo_tools, "popen_managed", fake_git)
    monkeypatch.setattr(repo_tools.subprocess, "run", incomplete_ripgrep)
    tools = RepositoryTools({
        "rag": {"extensions": [".py"]},
        "search": {"use_ripgrep_if_available": True},
    })
    tools._rg = "rg"
    tools.max_search_terms = 32

    query = " ".join(f"term{index}" for index in range(17))
    result = tools.search(str(tmp_path), query, limit=10, exact_count=True)

    assert git_calls == [True]
    assert rg_calls == []
    assert result["success"] is True, result
    assert result["count_exact"] is True
    assert result["total_matches"] == 1
    assert [item["path"] for item in result["results"]] == ["match.py"]


def test_exact_search_uses_simple_czech_ripgrep_candidates(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    (tmp_path / "match.py").write_text("word = 'řež'\n", encoding="utf-8")
    search_calls = []

    def run_query(command, **_kwargs):
        if command[0] == "rg":
            search_calls.append(command)
            return SimpleNamespace(returncode=0, stdout="match.py\n", stderr="")
        return SimpleNamespace(returncode=1, stdout=b"", stderr=b"")

    monkeypatch.setattr(repo_tools.subprocess, "run", run_query)
    tools = RepositoryTools({
        "rag": {"extensions": [".py"]},
        "search": {"use_ripgrep_if_available": True},
    })
    tools._rg = "rg"

    result = tools.search(str(tmp_path), "ŘEŽ", limit=10, exact_count=True)

    assert search_calls and any("rg" == call[0] for call in search_calls)
    assert result["success"] is True, result
    assert result["count_exact"] is True
    assert result["total_matches"] == 1
    assert [item["path"] for item in result["results"]] == ["match.py"]


def test_exact_search_keeps_multi_character_unicode_folds_on_git_scan(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    (tmp_path / "match.py").write_text("word = 'straße'\n", encoding="utf-8")
    monkeypatch.setattr(repo_tools, "popen_managed", lambda *_args, **_kwargs: _Process(b"match.py\0"))
    rg_calls = []

    def unexpected_ripgrep(*_args, **_kwargs):
        rg_calls.append(True)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(repo_tools.subprocess, "run", unexpected_ripgrep)
    tools = RepositoryTools({
        "rag": {"extensions": [".py"]},
        "search": {"use_ripgrep_if_available": True},
    })
    tools._rg = "rg"

    result = tools.search(str(tmp_path), "Straße", limit=10, exact_count=True)

    assert rg_calls == []
    assert result["success"] is True, result
    assert result["count_exact"] is True
    assert result["total_matches"] == 1
    assert [item["path"] for item in result["results"]] == ["match.py"]


def test_exact_ascii_query_matching_unicode_lower_expansion_uses_git_scan(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    (tmp_path / "match.py").write_text("word = 'İstanbul'\n", encoding="utf-8")
    monkeypatch.setattr(repo_tools, "popen_managed", lambda *_args, **_kwargs: _Process(b"match.py\0"))
    rg_calls = []

    def simple_fold_ripgrep(*_args, **_kwargs):
        rg_calls.append(True)
        # Unicode simple folding does not match Python's dotted-I lowercase expansion.
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(repo_tools.subprocess, "run", simple_fold_ripgrep)
    tools = RepositoryTools({
        "rag": {"extensions": [".py"]},
        "search": {"use_ripgrep_if_available": True},
    })
    tools._rg = "rg"

    result = tools.search(str(tmp_path), "i", limit=10, exact_count=True)

    assert rg_calls == []
    assert result["success"] is True, result
    assert result["count_exact"] is True
    assert result["total_matches"] == 1
    assert [item["path"] for item in result["results"]] == ["match.py"]


def test_identifier_search_diversifies_paths_without_changing_exact_paging(tmp_path):
    (tmp_path / "a_many.py").write_text(
        "\n".join(
            line
            for index in range(3)
            for line in (f"audit_needle = {index + 1}", *("" for _ in range(20)))
        ),
        encoding="utf-8",
    )
    (tmp_path / "z_docs.py").write_text("audit_needle = 'docs'\n", encoding="utf-8")
    tools = RepositoryTools({"rag": {"extensions": [".py"]}})

    first = tools.search(str(tmp_path), "audit_needle", limit=2, exact_count=True)
    second = tools.search(str(tmp_path), "audit_needle", limit=2, offset=2, exact_count=True)
    repeated_first = tools.search(str(tmp_path), "audit_needle", limit=2, exact_count=True)

    assert first["success"] is True, first
    assert first["count_exact"] is True
    assert first["total_matches"] == 4
    assert [item["path"] for item in first["results"]] == ["a_many.py", "z_docs.py"]
    assert second["total_matches"] == 4
    assert first["results"] == repeated_first["results"]
    all_hits = first["results"] + second["results"]
    assert len(all_hits) == first["total_matches"]
    assert len({(item["path"], item["start_line"]) for item in all_hits}) == 4
