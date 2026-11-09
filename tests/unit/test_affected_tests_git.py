import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from local_ai_hub.deterministic import DeterministicEngine


def test_failed_git_status_does_not_claim_no_changes(tmp_path, monkeypatch):
    engine = object.__new__(DeterministicEngine)
    engine._root = lambda root: root
    monkeypatch.setattr(subprocess, "run", Mock(return_value=subprocess.CompletedProcess(
        ["git"], 128, stdout="", stderr="fatal: not a git repository"
    )))
    result = engine.affected_tests(str(tmp_path), None)
    assert result["success"] is False
    assert result["error_code"] == "git_status_failed"
    assert result["exit_code"] == 128
    assert result["terminal"] is True and result["retryable"] is False
    assert "changed_files" not in result


@pytest.mark.parametrize(("failure", "code", "terminal", "retryable"), [
    (subprocess.TimeoutExpired(["git"], 5), "git_status_timeout", False, True),
    (FileNotFoundError("git unavailable"), "git_status_unavailable", True, False),
])
def test_git_status_exception_is_reported(tmp_path, monkeypatch, failure, code, terminal, retryable):
    engine = object.__new__(DeterministicEngine)
    engine._root = lambda root: root
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=failure))
    result = engine.affected_tests(str(tmp_path), None)
    assert result["success"] is False and result["error_code"] == code
    assert result["terminal"] is terminal and result["retryable"] is retryable
    if code == "git_status_timeout":
        assert result["timed_out"] is True
    assert "changed_files" not in result


@pytest.mark.parametrize(("old_name", "new_name"), [
    ("old name.py", "new name.py"), (".stará.py", ".nová.py"),
])
def test_git_rename_reports_both_real_paths(tmp_path, old_name, new_name):
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, timeout=10)

    git("init", "-q")
    (tmp_path / old_name).write_text("value = 1\n", encoding="utf-8")
    git("add", "--", old_name)
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@invalid", "commit", "--no-verify", "-qm", "fixture")
    git("mv", "--", old_name, new_name)
    engine = object.__new__(DeterministicEngine)
    engine._root = lambda root: root
    engine.test_matrix = Mock(return_value={"framework": "pytest", "test_files": []})
    engine.get_test_source_links = Mock(return_value=[])
    engine.code_index = SimpleNamespace(impact=lambda *_args: {"success": True, "graph_complete": True, "suggested_tests": []})
    result = engine.affected_tests(str(tmp_path), None)
    assert set(result["changed_files"]) == {old_name, new_name}


def test_git_status_lists_files_inside_untracked_directories(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=10)
    subprocess.run(["git", "config", "status.showUntrackedFiles", "no"], cwd=tmp_path, check=True, timeout=10)
    nested = tmp_path / "new package"
    nested.mkdir()
    (nested / "module.py").write_text("value = 1\n", encoding="utf-8")
    engine = object.__new__(DeterministicEngine)
    engine._root = lambda root: root
    engine.test_matrix = Mock(return_value={"framework": "pytest", "test_files": []})
    engine.get_test_source_links = Mock(return_value=[])
    engine.code_index = SimpleNamespace(impact=lambda *_args: {"success": True, "graph_complete": True, "suggested_tests": []})
    result = engine.affected_tests(str(tmp_path), None)
    assert result["changed_files"] == ["new package/module.py"]


@pytest.mark.parametrize("stdout", [b' M no-terminator', b'R  target.py\0', b'broken\0'])
def test_malformed_porcelain_is_not_no_changes(tmp_path, monkeypatch, stdout):
    engine = object.__new__(DeterministicEngine)
    engine._root = lambda root: root
    monkeypatch.setattr(subprocess, "run", Mock(return_value=subprocess.CompletedProcess(
        ["git"], 0, stdout=stdout, stderr=b""
    )))
    result = engine.affected_tests(str(tmp_path), None)
    assert result["success"] is False and result["error_code"] == "git_status_malformed"
    assert "changed_files" not in result


def test_git_status_preserves_leading_dot_in_filename(tmp_path, monkeypatch):
    engine = object.__new__(DeterministicEngine)
    engine._root = lambda root: root
    engine.test_matrix = Mock(return_value={"framework": "pytest", "test_files": []})
    engine.get_test_source_links = Mock(return_value=[])
    engine.code_index = SimpleNamespace(impact=lambda *_args: {"success": True, "graph_complete": True, "suggested_tests": []})
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=[
        subprocess.CompletedProcess(["git"], 0, stdout=b" M .hidden.py\0", stderr=b""),
        subprocess.CompletedProcess(["git"], 0, stdout=b"\n", stderr=b""),
    ]))
    result = engine.affected_tests(str(tmp_path), None)
    assert result["changed_files"] == [".hidden.py"]


def test_git_status_keeps_copy_source_and_target(tmp_path, monkeypatch):
    engine = object.__new__(DeterministicEngine)
    engine._root = lambda root: root
    engine.test_matrix = Mock(return_value={"framework": "pytest", "test_files": []})
    engine.get_test_source_links = Mock(return_value=[])
    engine.code_index = SimpleNamespace(impact=lambda *_args: {"success": True, "graph_complete": True, "suggested_tests": []})
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=[
        subprocess.CompletedProcess(["git"], 0, stdout=b"C  target file.py\0source file.py\0 M .hidden.py\0", stderr=b""),
        subprocess.CompletedProcess(["git"], 0, stdout=b"\n", stderr=b""),
    ]))
    result = engine.affected_tests(str(tmp_path), None)
    assert result["changed_files"] == ["target file.py", "source file.py", ".hidden.py"]
