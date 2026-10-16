import os
import stat
from pathlib import Path
from types import SimpleNamespace

from local_ai_hub import deterministic
from local_ai_hub.deterministic import DeterministicEngine


def test_compact_complexity_response_retains_incomplete_scope():
    from local_ai_hub import mcp_server

    raw = {
        "success": True, "complete": False, "scope": "bounded source sample",
        "files_analyzed": 50, "eligible_files": 51,
        "coverage": {"complete": False, "limits_hit": ["files"], "deadline_kind": "cooperative"},
        "functions": [{"name": "example", "file": "src/example.py"}],
    }
    token = mcp_server._CURRENT_RESPONSE_OPTIONS.set({
        "tool": "local_ai_repo", "max_response_tokens": 1800,
        "response_profile": "compact",
    })
    try:
        result = mcp_server._compact(raw, "complexity")
    finally:
        mcp_server._CURRENT_RESPONSE_OPTIONS.reset(token)
    assert result["success"] is True
    assert result["complete"] is False
    assert result["coverage"] == raw["coverage"]
    assert result["scope"] == raw["scope"]


def test_source_files_rank_ahead_of_history_copies(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "archive").mkdir()
    for number in range(60):
        (root / "archive" / f"copy_{number}.py").write_text(
            f"def historical_{number}():\n    return 1\n", encoding="utf-8"
        )
    for number in range(50):
        (root / f"legacy_{number:02}.py").write_text(
            f"def legacy_{number}():\n    return 1\n", encoding="utf-8"
        )
    (root / "src" / "important.py").write_text(
        "def important():\n    if ready:\n        return 1\n    return 0\n", encoding="utf-8"
    )

    result = DeterministicEngine().code_complexity(str(root))

    assert result["files_analyzed"] == 50
    assert any(item["file"] == "src/important.py" for item in result["functions"])
    assert result["complete"] is False
    assert "archive" in result["coverage"]["excluded_dirs"]
    assert result["coverage"]["limits_hit"] == ["files"]


def test_parse_error_makes_coverage_incomplete(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "bad.py").write_text("def broken(:\n    pass\n", encoding="utf-8")

    result = DeterministicEngine().code_complexity(str(root))

    assert result["files_analyzed"] == 0
    assert result["parse_error_count"] == 1
    assert result["complete"] is False


def test_explicit_path_outside_root_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("def outside():\n    return 1\n", encoding="utf-8")

    result = DeterministicEngine().code_complexity(str(root), str(outside))

    assert result["files_analyzed"] == 0
    assert result["complete"] is False
    assert result["read_error_count"] == 0


def test_reparse_point_attribute_is_rejected_without_native_junction(tmp_path: Path, monkeypatch) -> None:
    candidate = tmp_path / "ordinary.py"
    candidate.write_text("def ordinary():\n    return 1\n", encoding="utf-8")
    actual = os.lstat(candidate)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    monkeypatch.setattr(
        deterministic.os,
        "lstat",
        lambda _path: SimpleNamespace(st_mode=actual.st_mode, st_file_attributes=reparse_flag),
    )

    assert deterministic._is_symlink_or_reparse_point(candidate) is True


def test_complexity_uses_shared_root_archive_filters(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "current.py").write_text(
        "def current():\n    return 1\n", encoding="utf-8"
    )
    archived_paths = (
        "handoff/task-copy.py",
        ".sync-checks/task-copy.py",
        ".t17-merge-tmp/task-copy.py",
        "artifacts/handoff/task-copy.py",
    )
    for relative in archived_paths:
        archived = root / relative
        archived.parent.mkdir(parents=True, exist_ok=True)
        archived.write_text("def archived():\n    return 0\n", encoding="utf-8")

    result = DeterministicEngine().code_complexity(str(root))

    assert {item["file"] for item in result["functions"]} == {"src/current.py"}
    assert result["files_analyzed"] == 1
