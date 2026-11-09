from unittest.mock import Mock
import subprocess

import pytest

from local_ai_hub.deterministic import DeterministicEngine


@pytest.mark.parametrize(("marker", "expected"), [
    ("pyproject.toml", "pytest"), ("suite.sln", "dotnet"),
    ("package.json", "npm"), ("Cargo.toml", "cargo"),
    ("go.mod", "go"), (None, "unknown"),
])
def test_explicit_empty_paths_avoids_test_matrix_scan(tmp_path, marker, expected):
    if marker:
        (tmp_path / marker).write_text("", encoding="utf-8")
    engine = object.__new__(DeterministicEngine)
    engine._root = lambda root: root
    engine.test_matrix = Mock(side_effect=AssertionError("unnecessary test scan"))
    result = engine.affected_tests(str(tmp_path), [])
    assert result == {"success": True, "framework": expected, "changed_files": [],
                      "test_files": [], "suggested_command": "", "confidence": 1.0}
    engine.test_matrix.assert_not_called()


def test_no_git_changes_avoids_test_matrix_scan(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    engine = object.__new__(DeterministicEngine)
    engine._root = lambda root: root
    engine.test_matrix = Mock(side_effect=AssertionError("unnecessary test scan"))
    run = Mock(return_value=subprocess.CompletedProcess(["git"], 0, stdout=b"", stderr=b""))
    monkeypatch.setattr(subprocess, "run", run)
    result = engine.affected_tests(str(tmp_path), None)
    assert result["framework"] == "pytest" and result["changed_files"] == []
    run.assert_called_once()
    assert run.call_args.args[0] == ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", "."]
    engine.test_matrix.assert_not_called()


def test_empty_paths_preserve_framework_precedence(tmp_path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "suite.sln").write_text("", encoding="utf-8")
    engine = object.__new__(DeterministicEngine)
    engine._root = lambda root: root
    assert engine.affected_tests(str(tmp_path), [])["framework"] == "pytest"
