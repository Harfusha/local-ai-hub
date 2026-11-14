from pathlib import Path

from local_ai_hub.structural_search import search_structurally


def test_extracted_search_finds_python_declaration_in_requested_file(tmp_path: Path) -> None:
    (tmp_path / "example.py").write_text(
        "async def actual():\n    return 1\n", encoding="utf-8"
    )

    result = search_structurally(
        str(tmp_path),
        "fn:actual",
        path="example.py",
        max_results=30,
        is_symlink_or_reparse_point=lambda _path: False,
    )

    assert result["success"] is True
    assert result["count"] == 1
    assert result["matches"][0]["line"] == 1
