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
        assert result["requires_multiple_runners"] is True
        assert result["selection_complete"] is False
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


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        (["tests/integration.rs"], "cargo test --test integration"),
        ([r"tests\integration.rs"], "cargo test --test integration"),
        (["tests/unit.rs", "tests/api.rs"], "cargo test --test unit --test api"),
        (["src/lib.rs"], "cargo test"),
    ],
)
def test_cargo_command_selects_test_targets(paths, expected):
    assert affected_test_command(paths, "cargo") == expected


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        (["pkg/a/a_test.go"], "go test ./pkg/a"),
        ([r"pkg\a\a_test.go"], "go test ./pkg/a"),
        (["pkg/a/a_test.go", "pkg/b/b_test.go"], "go test ./pkg/a ./pkg/b"),
        (["a_test.go"], "go test ."),
    ],
)
def test_go_command_selects_packages_instead_of_source_files(paths, expected):
    assert affected_test_command(paths, "go") == expected


def test_dotnet_command_uses_fully_qualified_name_filter():
    assert affected_test_command(["Tests/UserTests.cs"], "dotnet") == (
        'dotnet test --filter "FullyQualifiedName~UserTests"'
    )


@pytest.mark.parametrize(
    ("framework", "composer", "phpunit_xml", "pest_config", "expected_command"),
    [
        ("phpunit", '{"require-dev":{"phpunit/phpunit":"^11"}}', False, False,
         "vendor/bin/phpunit tests/Unit/ExampleTest.php"),
        ("phpunit", "{}", True, False,
         "vendor/bin/phpunit tests/Unit/ExampleTest.php"),
        ("pest", '{"require-dev":{"pestphp/pest":"^3"}}', False, False,
         "vendor/bin/pest tests/Unit/ExampleTest.php"),
        ("pest", "{}", False, True,
         "vendor/bin/pest tests/Unit/ExampleTest.php"),
    ],
)
def test_php_test_matrix_detects_framework_and_builds_focused_command(
    tmp_path, framework, composer, phpunit_xml, pest_config, expected_command,
):
    root = tmp_path / "php-project"
    tests = root / "tests" / "Unit"
    tests.mkdir(parents=True)
    (root / "composer.json").write_text(composer, encoding="utf-8")
    if phpunit_xml:
        (root / "phpunit.xml").write_text("<phpunit/>", encoding="utf-8")
    if pest_config:
        (root / "tests" / "Pest.php").write_text("<?php\n", encoding="utf-8")
    (tests / "ExampleTest.php").write_text("<?php\n", encoding="utf-8")
    source = root / "src"
    source.mkdir()
    (source / "contest.php").write_text("<?php\n", encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    engine = DeterministicEngine(config, RepositoryTools(config))
    try:
        result = engine.test_matrix(str(root))
        assert result["framework"] == framework
        assert [item["path"] for item in result["test_files"]] == ["tests/Unit/ExampleTest.php"]
        assert affected_test_command(["tests/Unit/ExampleTest.php"], framework) == expected_command
    finally:
        observer = getattr(engine, "_cache_observer", None)
        if observer is not None:
            observer.close()
