"""Polyglot source scanning must include PHP and disclose bounded results."""
from __future__ import annotations

from local_ai_hub.structural_search import search_structurally


def _scan(root, pattern, **kwargs):
    return search_structurally(
        str(root), pattern, is_symlink_or_reparse_point=lambda path: path.is_symlink(), **kwargs
    )


def test_php_class_and_function_are_discovered_in_recursive_search(tmp_path):
    php = tmp_path / "src" / "InvoiceController.php"
    php.parent.mkdir()
    php.write_text(
        "<?php\nfinal class InvoiceController {\n public function calculateTotal(): int { return 5; }\n}\n",
        encoding="utf-8",
    )
    for pattern in ("class:InvoiceController", "fn:calculateTotal"):
        result = _scan(tmp_path, pattern)
        assert result["success"] is True
        assert any(item["file"] == "src/InvoiceController.php" for item in result["matches"])
        assert result["complete"] is True


def test_reaching_400_file_limit_is_never_reported_as_complete(tmp_path):
    for idx in range(401):
        (tmp_path / f"{idx:04d}.php").write_text(
            "<?php function lastTarget() {}\n" if idx == 400 else "<?php function other() {}\n",
            encoding="utf-8",
        )
    result = _scan(tmp_path, "fn:lastTarget")
    assert result["success"] is True
    assert result["count"] == 0
    assert result["truncated"] is True
    assert result["complete"] is False
    assert result["has_more"] is True
    assert "file_limit" in result["truncation_reasons"]
    assert result["unscanned_file_count"] is None


def test_exact_path_is_not_accidentally_clipped_by_file_budget(tmp_path):
    for idx in range(405):
        (tmp_path / f"{idx:04d}.php").write_text("<?php function target() {}\n", encoding="utf-8")
    result = _scan(tmp_path, "fn:target", path="0404.php")
    assert result["count"] == 1
    assert result["complete"] is True


def test_file_offset_resumes_past_400th_php_file(tmp_path):
    for idx in range(405):
        name = f"{idx:04d}.php"
        content = "<?php function needleAtEnd() {}\n" if idx == 404 else "<?php function irrelevant() {}\n"
        (tmp_path / name).write_text(content, encoding="utf-8")
    first = _scan(tmp_path, "fn:needleAtEnd")
    assert first["count"] == 0
    assert first["next_offset"] == 400
    second = _scan(tmp_path, "fn:needleAtEnd", file_offset=first["next_offset"])
    assert [x["file"] for x in second["matches"]] == ["0404.php"]
    assert second["next_offset"] is None
    assert second["complete"] is True


def test_invalid_file_offset_fails_closed(tmp_path):
    (tmp_path / "a.php").write_text("<?php function visible() {}\n", encoding="utf-8")
    for offset in (-1, 100001, True, "10", 1.2):
        result = _scan(tmp_path, "fn:visible", file_offset=offset)
        assert result["success"] is False
        assert result["status_code"] == 400
    assert _scan(tmp_path, "fn:visible", path="a.php", file_offset=1)["status_code"] == 400


def test_result_page_can_resume_within_single_php_file(tmp_path):
    source = tmp_path / "functions.php"
    source.write_text("<?php\n" + "".join("function needle() {}\n" for _ in range(11)), encoding="utf-8")
    offset = 0
    collected = []
    for _ in range(5):
        page = _scan(tmp_path, "fn:needle", max_results=3, match_offset=offset)
        collected.extend(item["line"] for item in page["matches"])
        if not page["has_more"]:
            assert page["complete"] is True
            break
        assert page["next_offset"] == 0
        assert "result_limit" in page["truncation_reasons"]
        offset = page["next_match_offset"]
    assert collected == list(range(2, 13))


def test_result_page_resumes_in_second_file_without_missing_matches(tmp_path):
    (tmp_path / "a.php").write_text("<?php function needle() {}\n", encoding="utf-8")
    (tmp_path / "b.php").write_text("<?php\n" + "function needle() {}\n" * 5, encoding="utf-8")
    (tmp_path / "c.php").write_text("<?php function needle() {}\n", encoding="utf-8")
    collected = []
    file_offset = match_offset = 0
    for _ in range(10):
        page = _scan(tmp_path, "fn:needle", max_results=2, file_offset=file_offset, match_offset=match_offset)
        collected.extend((item["file"], item["line"]) for item in page["matches"])
        if not page["has_more"]:
            break
        file_offset, match_offset = page["next_offset"], page["next_match_offset"]
    assert collected == [("a.php", 1)] + [("b.php", i) for i in range(2, 7)] + [("c.php", 1)]


def test_exact_php_path_matches_can_be_paged(tmp_path):
    (tmp_path / "a.php").write_text("<?php\n" + "function needle() {}\n" * 5, encoding="utf-8")
    first = _scan(tmp_path, "fn:needle", path="a.php", max_results=2)
    assert first["has_more"] is True
    assert first["next_offset"] is None
    assert first["next_match_offset"] == 2
    second = _scan(tmp_path, "fn:needle", path="a.php", max_results=2, match_offset=first["next_match_offset"])
    assert [item["line"] for item in second["matches"]] == [4, 5]


def test_structural_search_bounded_result_and_match_offsets(tmp_path):
    (tmp_path / "a.php").write_text("<?php function needle() {}\n", encoding="utf-8")
    for kwargs in ({"max_results": 0}, {"max_results": True}, {"max_results": 1001}, {"max_results": "4"},
                   {"match_offset": -1}, {"match_offset": True}, {"match_offset": "1"}, {"match_offset": 100001}):
        response = _scan(tmp_path, "fn:needle", **kwargs)
        assert response["success"] is False
        assert response["status_code"] == 400


def test_mcp_structural_search_cursor_contract():
    from local_ai_hub.operation_contracts import validate_operation_arguments
    assert validate_operation_arguments("local_ai_repo", "structural_search", {
        "root": "/repo", "query": "fn:needle", "offset": 400, "match_offset": 2,
    }) is None
