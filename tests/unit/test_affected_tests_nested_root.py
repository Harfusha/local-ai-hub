import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from local_ai_hub.deterministic import DeterministicEngine


def test_git_discovery_is_confined_to_requested_subdirectory(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=10)
    scope = tmp_path / "scope"
    scope.mkdir()
    (scope / "inside.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "outside.py").write_text("x=2\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", "scope/inside.py", "outside.py"], cwd=tmp_path, check=True, timeout=10)
    engine = object.__new__(DeterministicEngine)
    engine._root = lambda root: root
    engine.test_matrix = Mock(return_value={"framework": "pytest", "test_files": []})
    engine.get_test_source_links = Mock(return_value=[])
    engine.code_index = SimpleNamespace(impact=lambda *_args: {"success": True, "graph_complete": True, "suggested_tests": []})
    result = engine.affected_tests(str(scope), None)
    assert result["changed_files"] == ["inside.py"]


@pytest.mark.parametrize("direction", ["into", "out_of"])
def test_rename_across_scope_boundary_never_returns_outside_path(tmp_path, direction):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, timeout=10)
    git("init", "-q")
    scope = tmp_path / "scope"
    scope.mkdir()
    source = "outside.py" if direction == "into" else "scope/inside.py"
    target = "scope/inside.py" if direction == "into" else "outside.py"
    (tmp_path / source).write_text("value = 1\n", encoding="utf-8")
    git("add", "--", source)
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@invalid", "commit", "--no-verify", "-qm", "fixture")
    git("mv", "--", source, target)
    engine = object.__new__(DeterministicEngine)
    engine._root = lambda root: root
    engine.test_matrix = Mock(return_value={"framework": "pytest", "test_files": []})
    engine.get_test_source_links = Mock(return_value=[])
    engine.code_index = SimpleNamespace(impact=lambda *_args: {"success": True, "graph_complete": True, "suggested_tests": []})
    result = engine.affected_tests(str(scope), None)
    assert result["changed_files"] == ["inside.py"]


@pytest.mark.parametrize("stdout,returncode", [(b"scope", 0), (b"", 0), (b"scope/\n", 1)])
def test_invalid_git_prefix_is_reported(tmp_path, monkeypatch, stdout, returncode):
    engine = object.__new__(DeterministicEngine)
    engine._root = lambda root: root
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=[
        subprocess.CompletedProcess(["git"], 0, stdout=b" M file.py\0", stderr=b""),
        subprocess.CompletedProcess(["git"], returncode, stdout=stdout, stderr=b""),
    ]))
    result = engine.affected_tests(str(tmp_path), None)
    assert result["success"] is False and result["error_code"] == "git_prefix_failed"
