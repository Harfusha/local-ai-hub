import ast
import os
from pathlib import Path

import pytest

from local_ai_hub.deterministic import DeterministicEngine


def test_structural_search_reports_incomplete_400_file_scan(tmp_path: Path, monkeypatch) -> None:
    filenames = [f"source_{index:03}.py" for index in range(401)]
    for filename in filenames:
        (tmp_path / filename).write_text("needle\n" if filename == filenames[-1] else "pass\n", encoding="utf-8")
    monkeypatch.setattr(
        "local_ai_hub.deterministic.os.walk",
        lambda _root, **_kwargs: iter([(str(tmp_path), [], filenames)]),
    )

    result = DeterministicEngine().structural_search(str(tmp_path), pattern="needle")

    assert result["success"] is True
    assert result["files_scanned"] == 400
    assert result["matches"] == []
    assert result["truncated"] is True
    assert result["truncation_reasons"] == ["file_limit"]


def test_structural_search_only_reports_result_limit_when_match_is_omitted(tmp_path: Path) -> None:
    source = tmp_path / "one.ts"
    source.write_text("needle\nother\n", encoding="utf-8")
    engine = DeterministicEngine()

    exact = engine.structural_search(str(tmp_path), pattern="needle", path="one.ts", max_results=1)
    assert exact["count"] == 1
    assert exact["truncated"] is False

    source.write_text("needle\nneedle\n", encoding="utf-8")
    capped = engine.structural_search(str(tmp_path), pattern="needle", path="one.ts", max_results=1)
    assert capped["count"] == 1
    assert capped["truncated"] is True
    assert capped["truncation_reasons"] == ["result_limit"]


def test_structural_search_marks_syntax_fallback_partial(tmp_path: Path) -> None:
    source = tmp_path / "broken.py"
    source.write_text("def broken(:\n    needle()\n", encoding="utf-8")

    result = DeterministicEngine().structural_search(str(tmp_path), pattern="needle", path="broken.py")

    assert result["parse_errors"] == 1
    assert result["truncated"] is True
    assert result["truncation_reasons"] == ["parse_errors"]
    assert len(result["matches"]) == 1


def test_structural_search_marks_file_read_failure_partial(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "blocked.ts"
    source.write_text("needle\n", encoding="utf-8")
    original_open = os.open

    def denied_open(path, *args, **kwargs):
        if isinstance(path, (str, os.PathLike)) and Path(path) == source:
            raise PermissionError("private path detail")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr("local_ai_hub.deterministic.os.open", denied_open)
    result = DeterministicEngine().structural_search(str(tmp_path), pattern="needle", path="blocked.ts")

    assert result["read_errors"] == 1
    assert result["truncated"] is True
    assert result["truncation_reasons"] == ["read_errors"]
    assert "private path detail" not in str(result)


def test_structural_search_skips_absolute_path_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("needle()\n", encoding="utf-8")

    result = DeterministicEngine().structural_search(str(root), pattern="needle", path=str(outside))

    assert result["success"] is False
    assert result["status_code"] == 403
    assert not result.get("matches")


def test_structural_search_does_not_swallow_unexpected_parser_failure(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "valid.py"
    source.write_text("needle()\n", encoding="utf-8")

    def broken_parser(*_args, **_kwargs):
        raise RuntimeError("parser bug")

    monkeypatch.setattr("local_ai_hub.deterministic.ast.parse", broken_parser)
    with pytest.raises(RuntimeError, match="parser bug"):
        DeterministicEngine().structural_search(str(tmp_path), pattern="needle", path="valid.py")


def test_recursive_declaration_search_skips_irrelevant_python_parses(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "irrelevant.py").write_text("def other():\n    return 1\n", encoding="utf-8")
    (tmp_path / "target.py").write_text("def wanted():\n    return 2\n", encoding="utf-8")
    parsed_files: list[str] = []
    original_parse = ast.parse

    def tracking_parse(source, filename="<unknown>", *args, **kwargs):
        if filename in {"irrelevant.py", "target.py"}:
            parsed_files.append(filename)
        return original_parse(source, filename, *args, **kwargs)

    monkeypatch.setattr("local_ai_hub.deterministic.ast.parse", tracking_parse)

    result = DeterministicEngine().structural_search(str(tmp_path), pattern="fn:wanted")

    assert result["count"] == 1
    assert parsed_files == ["target.py"]


def test_recursive_call_search_skips_python_files_without_target_name(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "irrelevant.py").write_text("def other():\n    return 1\n", encoding="utf-8")
    (tmp_path / "target.py").write_text("def run():\n    wanted()\n", encoding="utf-8")
    parsed_files: list[str] = []
    original_parse = ast.parse

    def tracking_parse(source, filename="<unknown>", *args, **kwargs):
        if filename in {"irrelevant.py", "target.py"}:
            parsed_files.append(filename)
        return original_parse(source, filename, *args, **kwargs)

    monkeypatch.setattr("local_ai_hub.deterministic.ast.parse", tracking_parse)

    result = DeterministicEngine().structural_search(str(tmp_path), pattern="call:wanted")

    assert result["count"] == 1
    assert parsed_files == ["target.py"]
