from pathlib import Path

import pytest

from local_ai_hub.deterministic import DeterministicEngine


def test_structural_search_reports_incomplete_400_file_scan(tmp_path: Path, monkeypatch) -> None:
    filenames = [f"source_{index:03}.py" for index in range(401)]
    for filename in filenames:
        (tmp_path / filename).write_text("needle\n" if filename == filenames[-1] else "pass\n", encoding="utf-8")
    monkeypatch.setattr(
        "local_ai_hub.deterministic.os.walk",
        lambda _root: iter([(str(tmp_path), [], filenames)]),
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
    original_read_text = Path.read_text

    def denied_read(path: Path, *args, **kwargs):
        if path == source:
            raise PermissionError("private path detail")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied_read)
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

    assert result["success"] is True
    assert result["matches"] == []
    assert result["files_scanned"] == 0


def test_structural_search_does_not_swallow_unexpected_parser_failure(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "valid.py"
    source.write_text("needle()\n", encoding="utf-8")

    def broken_parser(*_args, **_kwargs):
        raise RuntimeError("parser bug")

    monkeypatch.setattr("local_ai_hub.deterministic.ast.parse", broken_parser)
    with pytest.raises(RuntimeError, match="parser bug"):
        DeterministicEngine().structural_search(str(tmp_path), pattern="needle", path="valid.py")
