from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from local_ai_hub.split_changes import run_split_changes


def _git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root)


def _plan(root: Path, paths=None):
    return run_split_changes(
        SimpleNamespace(_root=lambda value: value, git_status_timeout=10),
        str(root), paths, path_type=Path, subprocess_module=subprocess,
        hidden_run_kwargs_fn=lambda: {},
    )


def _repo(root: Path) -> None:
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    (root / "tests").mkdir()
    for path in ("payment.py", "tests/test_payment.py", "cache.py"):
        (root / path).write_text("original\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "initial")


def test_component_groups_and_index_preservation(tmp_path):
    _repo(tmp_path)
    (tmp_path / "payment.py").write_text("staged\n", encoding="utf-8")
    _git(tmp_path, "add", "payment.py")
    (tmp_path / "payment.py").write_text("unstaged\n", encoding="utf-8")
    (tmp_path / "tests/test_payment.py").write_text("test changed\n", encoding="utf-8")
    (tmp_path / "cache.py").write_text("cache changed\n", encoding="utf-8")
    (tmp_path / "new file.py").write_text("new\n", encoding="utf-8")
    before = _git(tmp_path, "diff", "--cached", "--binary")
    result = _plan(tmp_path)
    assert result["success"]
    assert result["total_files"] == 4
    assert result["cluster_count"] == 3
    payment = next(g for g in result["clusters"] if "payment.py" in g["files"])
    assert payment["files"] == ["payment.py", "tests/test_payment.py"]
    assert "mixed_staged_unstaged" in payment["risks"]
    assert payment["changes"][0]["staged_lines"] == [1, 1]
    assert payment["changes"][0]["unstaged_lines"] == [1, 1]
    assert result["commit_ready"] is False
    assert _git(tmp_path, "diff", "--cached", "--binary") == before
    assert _plan(tmp_path)["clusters"] == result["clusters"]


def test_clean_invalid_and_scoped(tmp_path):
    assert not _plan(tmp_path)["success"]
    _repo(tmp_path)
    assert _plan(tmp_path)["clusters"] == []
    (tmp_path / "cache.py").write_text("changed\n", encoding="utf-8")
    assert _plan(tmp_path, ["cache.py"])["total_files"] == 1
    assert not _plan(tmp_path, ["missing.py"])["success"]


def test_ambiguous_test_stays_separate(tmp_path):
    _repo(tmp_path)
    (tmp_path / "other").mkdir()
    (tmp_path / "other/payment.py").write_text("original\n", encoding="utf-8")
    _git(tmp_path, "add", "other/payment.py")
    _git(tmp_path, "commit", "-m", "second")
    for path in ("payment.py", "other/payment.py", "tests/test_payment.py"):
        (tmp_path / path).write_text("changed\n", encoding="utf-8")
    assert _plan(tmp_path)["cluster_count"] == 3
