from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace

from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.deterministic_test_paths import extract_test_case_names, is_test_matrix_source
from local_ai_hub.test_matrix_commands import build_test_file_command


def _engine(tmp_path: Path) -> DeterministicEngine:
    return DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})


def test_test_matrix_uses_only_current_regular_contained_test_files(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    test_dir = repo_root / "tests"
    test_dir.mkdir(parents=True)
    current = test_dir / "test_current.py"
    current.write_text("def test_current_case(): pass\n", encoding="utf-8")
    outside = tmp_path / "test_outside.py"
    outside.write_text("def test_outside_case(): pass\n", encoding="utf-8")
    missing = test_dir / "test_deleted.py"
    engine = _engine(repo_root)
    snapshot_stat = current.stat()

    def candidates(*_args, **_kwargs):
        yield current, snapshot_stat
        yield missing, snapshot_stat
        yield outside, outside.stat()

    monkeypatch.setattr(engine.repo_tools, "_iter_files_with_stat", candidates)
    monkeypatch.setattr(engine, "_connect", lambda: (_ for _ in ()).throw(AssertionError("stale index consulted")))

    result = engine.test_matrix(str(repo_root))

    assert [item["path"] for item in result["test_files"]] == ["tests/test_current.py"]
    assert result["test_files"][0]["cases"] == ["test_current_case"]
    assert result["test_files"][0]["cases_scan_complete"] is True
    assert result["test_files"][0]["case_detection"] == "python_test_function_name_heuristic"
    assert result["coverage"]["scan_complete"] is False
    assert result["coverage"]["scope"] == "current supported test files emitted by repo_tools iterator"
    assert result["coverage"]["max_depth"] == 25
    assert result["coverage"]["inventory_omissions_unknown"] is True


def test_test_matrix_reports_lexical_case_cap_as_incomplete(tmp_path: Path) -> None:
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    test_file = test_dir / "test_many.py"
    test_file.write_text("".join(f"def test_case_{index}(): pass\n" for index in range(20)), encoding="utf-8")
    result = _engine(tmp_path).test_matrix(str(tmp_path))

    row = result["test_files"][0]
    assert row["cases_count"] == 16
    assert len(row["cases"]) == 15
    assert row["cases_truncated"] is True
    assert row["cases_scan_complete"] is False
    assert row["case_detection"] == "python_test_function_name_heuristic"
    assert "test_case_result_limit_reached" in result["coverage"]["warnings"]


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
    python_test = test_dir / "test py.py"
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
    files = {item["path"]: item for item in result["test_files"]}
    assert files["tests/test py.py"]["run_command"] == ""
    assert files["tests/test py.py"]["run_argv"] == ["python", "-m", "pytest", "--", "tests/test py.py"]
    assert files["tests/TestCs.cs"]["run_command"] == ""
    assert files["tests/TestCs.cs"]["run_argv"] == []

    original_read = engine.repo_tools._read_snapshot

    def changed_read(path: Path, **kwargs):
        digest, lines = original_read(path, **kwargs)
        if path == python_test:
            path.write_text("def test_changed(): pass\n", encoding="utf-8")
        return digest, lines

    monkeypatch.setattr(engine.repo_tools, "_read_snapshot", changed_read)
    result = engine.test_matrix(str(tmp_path))
    assert "tests/test py.py" not in [item["path"] for item in result["test_files"]]
    assert result["coverage"]["scan_complete"] is False


def test_test_matrix_read_ceiling_is_prevalidated_size_plus_lookahead(tmp_path: Path, monkeypatch) -> None:
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    test_file = test_dir / "test_growth.py"
    test_file.write_text("def test_case(): pass\n", encoding="utf-8")
    engine = _engine(tmp_path)
    original_stat = test_file.stat()
    original_read = engine.repo_tools._read_snapshot
    requested_limits = []

    def candidates(*_args, **_kwargs):
        yield test_file, original_stat

    def grow_before_bounded_read(path: Path, *, stat=None, max_bytes=None):
        requested_limits.append(max_bytes)
        path.write_bytes(path.read_bytes() + b"#")
        return original_read(path, stat=stat, max_bytes=max_bytes)

    monkeypatch.setattr(engine.repo_tools, "_iter_files_with_stat", candidates)
    monkeypatch.setattr(engine.repo_tools, "_read_snapshot", grow_before_bounded_read)
    result = engine.test_matrix(str(tmp_path))

    assert requested_limits == [original_stat.st_size]
    assert result["test_files"] == []
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


def test_test_matrix_passes_deadline_to_inventory_and_surfaces_inventory_timeout(
    tmp_path: Path, monkeypatch
) -> None:
    engine = _engine(tmp_path)
    observed = {}

    def candidates(_root, *, max_depth, max_files, inventory_status=None, inventory_deadline=None):
        observed.update(
            max_depth=max_depth,
            max_files=max_files,
            inventory_status=inventory_status,
            inventory_deadline=inventory_deadline,
        )
        if inventory_status is not None:
            inventory_status["complete"] = False
            inventory_status["reasons"].append("time_limit")
        return iter(())

    monkeypatch.setattr(engine.repo_tools, "_iter_files_with_stat", candidates)

    result = engine.test_matrix(str(tmp_path))

    assert observed["inventory_deadline"] is not None
    assert observed["inventory_status"] is not None
    assert result["coverage"]["scan_complete"] is False
    assert "test_file_enumeration_deadline_exceeded" in result["coverage"]["warnings"]


def test_test_matrix_command_builder_preserves_runner_and_display_rules() -> None:
    assert build_test_file_command(Path("tests/test_api.py"), "tests/test_api.py", "pytest") == (
        ["python", "-m", "pytest", "--", "tests/test_api.py"],
        "python -m pytest -- tests/test_api.py",
    )
    assert build_test_file_command(Path("Tests/Widget.cs"), "Tests/Widget.cs", "dotnet") == (
        ["dotnet", "test", "--filter", "FullyQualifiedName~Widget"],
        "",
    )
    assert build_test_file_command(Path("src/example.test.ts"), "src/example.test.ts", "npm") == (
        ["npm", "test", "--", "src/example.test.ts"],
        "npm test -- src/example.test.ts",
    )
    assert build_test_file_command(Path("pkg/example_test.go"), "pkg/example_test.go", "go") == (
        ["go", "test", "./pkg"],
        "go test ./pkg",
    )
    assert build_test_file_command(Path("src/lib.rs"), "src/lib.rs", "cargo") == (
        ["cargo", "test"],
        "cargo test",
    )


def test_test_matrix_command_builder_keeps_argv_when_display_path_needs_quoting() -> None:
    assert build_test_file_command(Path("tests/test file.py"), "tests/test file.py", "pytest") == (
        ["python", "-m", "pytest", "--", "tests/test file.py"],
        "",
    )


def test_test_matrix_command_builder_rejects_unknown_framework_pair() -> None:
    assert build_test_file_command(Path("tests/test.py"), "tests/test.py", "npm") == ([], "")


def test_test_matrix_source_classifier_preserves_supported_names_and_extensions() -> None:
    assert is_test_matrix_source("tests/test_current.py")
    assert is_test_matrix_source("test_widget.CS")
    assert is_test_matrix_source("src/widget_test.go")
    assert is_test_matrix_source("src/tests_helper.java")
    assert is_test_matrix_source("specs/client.test.TS")
    assert is_test_matrix_source("src/WidgetTest.php")
    assert is_test_matrix_source("src/widget_test.php")
    assert is_test_matrix_source("src/test.php")
    assert is_test_matrix_source("specs/helper.c")


def test_test_matrix_source_classifier_preserves_exclusions() -> None:
    assert not is_test_matrix_source("tests/Pest.php")
    assert not is_test_matrix_source("tests/README.md")
    assert not is_test_matrix_source("src/widget.cs")
    assert not is_test_matrix_source("src/widgettest.php")


def test_test_case_extractor_keeps_python_heuristic_and_order() -> None:
    cases, complete = extract_test_case_names(
        "def test_first(): pass\nasync def test_ignored(): pass\n    def test_second(x): pass\n",
        ".py",
    )
    assert cases == ["test_first", "test_second"]
    assert complete is True


def test_test_case_extractor_keeps_csharp_attribute_window() -> None:
    cases, complete = extract_test_case_names(
        "[Fact]\npublic void Works() {}\n[UnityTest]\nvoid AlsoWorks() {}\n",
        ".cs",
    )
    assert cases == ["Works", "AlsoWorks"]
    assert complete is True


def test_test_case_extractor_caps_names_and_reports_incomplete_scan() -> None:
    source = "".join(f"def test_case_{index}(): pass\n" for index in range(20))
    cases, complete = extract_test_case_names(source, ".py")
    assert cases == [f"test_case_{index}" for index in range(16)]
    assert complete is False


def test_test_case_extractor_stops_when_deadline_callback_expires() -> None:
    checks = 0

    def should_continue() -> bool:
        nonlocal checks
        checks += 1
        return checks <= 2

    cases, complete = extract_test_case_names(
        "def test_first(): pass\ndef test_second(): pass\ndef test_third(): pass\n",
        ".py",
        should_continue=should_continue,
    )
    assert cases == ["test_first", "test_second"]
    assert complete is False
