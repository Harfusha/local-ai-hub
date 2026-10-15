from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace

from local_ai_hub.deterministic import DeterministicEngine


def _engine(tmp_path: Path) -> DeterministicEngine:
    return DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})


def test_test_matrix_uses_only_current_regular_contained_test_files(tmp_path: Path, monkeypatch) -> None:
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    current = test_dir / "test_current.py"
    current.write_text("def test_current_case(): pass\n", encoding="utf-8")
    outside = tmp_path.parent / "test_outside.py"
    outside.write_text("def test_outside_case(): pass\n", encoding="utf-8")
    missing = test_dir / "test_deleted.py"
    engine = _engine(tmp_path)
    snapshot_stat = current.stat()

    def candidates(*_args, **_kwargs):
        yield current, snapshot_stat
        yield missing, snapshot_stat
        yield outside, outside.stat()

    monkeypatch.setattr(engine.repo_tools, "_iter_files_with_stat", candidates)
    monkeypatch.setattr(engine, "_connect", lambda: (_ for _ in ()).throw(AssertionError("stale index consulted")))

    result = engine.test_matrix(str(tmp_path))

    assert [item["path"] for item in result["test_files"]] == ["tests/test_current.py"]
    assert result["test_files"][0]["cases"] == ["test_current_case"]
    assert result["coverage"]["scan_complete"] is False


def test_test_matrix_omits_reparse_point_and_unreadable_file(tmp_path: Path, monkeypatch) -> None:
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    test_file = test_dir / "test_unreadable.py"
    test_file.write_text("def test_case(): pass\n", encoding="utf-8")
    engine = _engine(tmp_path)
    original_lstat = Path.lstat

    def candidates(*_args, **_kwargs):
        yield test_file, test_file.stat()

    def reparse_lstat(path: Path):
        if path == test_file:
            return SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400)
        return original_lstat(path)

    monkeypatch.setattr(engine.repo_tools, "_iter_files_with_stat", candidates)
    monkeypatch.setattr(Path, "lstat", reparse_lstat)
    result = engine.test_matrix(str(tmp_path))
    assert result["test_files"] == []
    assert "test_file_reparse_point_skipped" in result["coverage"]["warnings"]

    monkeypatch.setattr(Path, "lstat", original_lstat)
    monkeypatch.setattr(engine.repo_tools, "_read_snapshot", lambda *_a, **_k: (_ for _ in ()).throw(OSError("unreadable")))
    result = engine.test_matrix(str(tmp_path))
    assert result["test_files"] == []
    assert result["coverage"]["scan_complete"] is False


def test_test_matrix_omits_changed_file_and_mixed_language_wrong_runner(tmp_path: Path, monkeypatch) -> None:
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    python_test = test_dir / "test_py.py"
    python_test.write_text("def test_py_case(): pass\n", encoding="utf-8")
    cs_test = test_dir / "TestCs.cs"
    cs_test.write_text("public class TestCs { [Fact] public void Works() {} }\n", encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    engine = _engine(tmp_path)

    def candidates(*_args, **_kwargs):
        for path in (python_test, cs_test):
            yield path, path.stat()

    monkeypatch.setattr(engine.repo_tools, "_iter_files_with_stat", candidates)
    result = engine.test_matrix(str(tmp_path))
    commands = {item["path"]: item["run_command"] for item in result["test_files"]}
    assert commands["tests/test_py.py"] == "python -m pytest tests/test_py.py"
    assert commands["tests/TestCs.cs"] == ""

    original_read = engine.repo_tools._read_snapshot

    def changed_read(path: Path, **kwargs):
        digest, lines = original_read(path, **kwargs)
        if path == python_test:
            path.write_text("def test_changed(): pass\n", encoding="utf-8")
        return digest, lines

    monkeypatch.setattr(engine.repo_tools, "_read_snapshot", changed_read)
    result = engine.test_matrix(str(tmp_path))
    assert "tests/test_py.py" not in [item["path"] for item in result["test_files"]]
    assert result["coverage"]["scan_complete"] is False


def test_test_matrix_caps_target_count_and_file_bytes(tmp_path: Path, monkeypatch) -> None:
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    paths = []
    for index in range(41):
        path = test_dir / f"test_{index:02d}.py"
        path.write_text("def test_case(): pass\n", encoding="utf-8")
        paths.append(path)
    too_large = test_dir / "test_large.py"
    too_large.write_bytes(b"x" * 256_001)
    engine = _engine(tmp_path)

    limits = {}

    def candidates(*_args, **kwargs):
        limits.update(kwargs)
        for path in [too_large, *paths]:
            yield path, path.stat()

    monkeypatch.setattr(engine.repo_tools, "_iter_files_with_stat", candidates)
    result = engine.test_matrix(str(tmp_path))
    assert result["test_files_count"] == 40
    assert result["coverage"]["scan_complete"] is False
    assert "test_file_result_limit_reached" in result["coverage"]["warnings"]
    assert "test_file_invalid_or_too_large_skipped" in result["coverage"]["warnings"]
    assert limits["max_files"] == 2000
    assert limits["max_depth"] == 25
    assert all(len(item.get("content_sha256", "")) == 64 for item in result["test_files"])
