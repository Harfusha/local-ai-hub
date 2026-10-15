"""Regression source only: execution belongs to the final implementation-bundle gate."""
from types import SimpleNamespace

import pytest

from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.test_selection import affected_test_command, compatible_tests


def test_mixed_affected_files_do_not_send_js_fixture_to_pytest(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    index = SimpleNamespace(impact=lambda *_args: {
        "success": True, "graph_complete": True, "suggested_tests": [],
    })
    engine = DeterministicEngine(config, RepositoryTools(config), code_index=index)
    monkeypatch.setattr(engine, "test_matrix", lambda _root: {
        "framework": "pytest", "test_files": [
            {"path": "tests/a space/test_thing.py"}, {"path": "tests/thing.test.js"},
        ],
    })
    monkeypatch.setattr(engine, "get_test_source_links", lambda *_args: [])
    try:
        result = engine.affected_tests(str(root), ["src/thing.py"])
        assert result["test_files"] == ["tests/a space/test_thing.py"]
        assert result["excluded_incompatible_tests"] == ["tests/thing.test.js"]
        assert ".js" not in result["suggested_command"]
        assert "test_thing.py" in result["suggested_command"]
        assert "\"tests/a space/test_thing.py\"" in result["suggested_command"] or "'tests/a space/test_thing.py'" in result["suggested_command"]
    finally:
        observer = getattr(engine, "_cache_observer", None)
        if observer is not None:
            observer.close()


@pytest.mark.parametrize("runner,selected", [
    ("pytest", ["test_a.py"]), ("vitest", ["a.test.mts", "a.test.js"]),
    ("dotnet", ["Tests.cs"]), ("cargo", ["a.rs"]), ("go", ["a_test.go"]),
    ("unknown", []),
])
def test_runner_compatibility_preserves_only_consumable_paths(runner, selected):
    paths = ["test_a.py", "a.test.mts", "a.test.js", "Tests.cs", "a.rs", "a_test.go", "fixture.json"]
    actual, excluded = compatible_tests(paths, runner)
    assert actual == selected
    assert set(actual).isdisjoint(excluded)
    assert set(actual) | set(excluded) == set(paths)


def test_leading_dash_cannot_become_pytest_option():
    command = affected_test_command(["-surprise.py", "fixture.js"], "pytest")
    assert command == "pytest ./-surprise.py"
    assert affected_test_command(["fixture.json"], "unknown") == ""
