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


def test_mcp_structural_search_match_offset_is_in_public_schema():
    from local_ai_hub.operation_contracts import operation_parameters_schema, validate_operation_arguments

    properties = operation_parameters_schema("local_ai_repo")["properties"]
    assert properties["match_offset"]["type"] == "integer"
    assert properties["match_offset"]["minimum"] == 0
    assert properties["match_offset"]["maximum"] == 100_000
    assert validate_operation_arguments("local_ai_repo", "structural_search", {
        "root": "/repo", "query": "fn:needle", "offset": 0, "match_offset": -1,
    }) is not None
    assert validate_operation_arguments("local_ai_repo", "search", {
        "root": "/repo", "query": "needle", "match_offset": 1,
    }) is not None


def test_mcp_structural_search_large_repository_file_offset_schema():
    from local_ai_hub.operation_contracts import operation_parameters_schema, validate_operation_arguments

    properties = operation_parameters_schema("local_ai_repo")["properties"]
    assert properties["file_offset"]["maximum"] == 100_000
    assert properties["offset"]["maximum"] < properties["file_offset"]["maximum"]
    assert validate_operation_arguments("local_ai_repo", "structural_search", {
        "root": "/repo", "query": "fn:needle", "file_offset": 8000, "match_offset": 3,
    }) is None
    assert validate_operation_arguments("local_ai_repo", "structural_search", {
        "root": "/repo", "query": "fn:needle", "file_offset": -1,
    }) is not None
    assert validate_operation_arguments("local_ai_repo", "search", {
        "root": "/repo", "query": "needle", "file_offset": 8000,
    }) is not None


def test_c_family_function_and_class_queries_ignore_multiline_comments_and_strings(tmp_path):
    script = tmp_path / "app.ts"
    script.write_text(
        '/* class TargetFake { }\n'
        'function TargetFake() {} */\n'
        'const example = "function TargetFake() {}";\n'
        'const template = `class TargetFake {}`;\n'
        '// function TargetFake() {}\n'
        '/* start */ class ActualTarget {}\n'
        'function ActualFunction() {} // class TargetFake {}\n',
        encoding="utf-8",
    )
    assert _scan(tmp_path, "class:TargetFake")["matches"] == []
    assert _scan(tmp_path, "fn:TargetFake")["matches"] == []
    assert [(m["file"], m["line"]) for m in _scan(tmp_path, "class:ActualTarget")["matches"]] == [("app.ts", 6)]
    assert [(m["file"], m["line"]) for m in _scan(tmp_path, "fn:ActualFunction")["matches"]] == [("app.ts", 7)]


def test_php_class_and_function_queries_ignore_markup_and_comments(tmp_path):
    source = tmp_path / "page.php"
    source.write_text(
        '<div>class FakeMarkup {}</div>\n'
        '<?php\n'
        '# function NotReal() {}\n'
        '$text = "class FakeMarkup {}";\n'
        '/* function NotReal() {} */\n'
        'class RealClass {}\n'
        'function real_function() {}\n'
        '?>\n'
        '<div>function NotReal() {}</div>\n',
        encoding="utf-8",
    )
    assert _scan(tmp_path, "class:FakeMarkup")["matches"] == []
    assert _scan(tmp_path, "fn:NotReal")["matches"] == []
    assert [m["line"] for m in _scan(tmp_path, "class:RealClass")["matches"]] == [6]
    assert [m["line"] for m in _scan(tmp_path, "fn:real_function")["matches"]] == [7]


def test_typescript_function_search_supports_assigned_arrow_and_function_expressions(tmp_path):
    source = tmp_path / "functions.ts"
    source.write_text(
        "export const compute = (left: number, right: number) => left + right;\n"
        "const fetchData = async (id: string) => id;\n"
        "let regular = function() { return 1; };\n"
        "const inline = async value => value;\n"
        'const misleading = "const fake = () => 2";\n'
        "// const ignored = () => 2;\n",
        encoding="utf-8",
    )
    for name, line in (("compute", 1), ("fetchData", 2), ("regular", 3), ("inline", 4)):
        assert [item["line"] for item in _scan(tmp_path, f"fn:{name}")["matches"]] == [line]
    assert _scan(tmp_path, "fn:fake")["matches"] == []
    assert _scan(tmp_path, "fn:ignored")["matches"] == []


def test_go_function_search_supports_receiver_methods(tmp_path):
    source = tmp_path / "widget.go"
    source.write_text(
        "package widget\n"
        "func (w *Widget) Handle(ctx Context) {}\n"
        "func Standalone() {}\n"
        'var text = "func (w *Widget) Fake() {}"\n',
        encoding="utf-8",
    )
    assert [item["line"] for item in _scan(tmp_path, "fn:Handle")["matches"]] == [2]
    assert [item["line"] for item in _scan(tmp_path, "fn:Standalone")["matches"]] == [3]
    assert _scan(tmp_path, "fn:Fake")["matches"] == []


def test_structural_search_returns_explicit_http_error_codes(tmp_path):
    from types import SimpleNamespace
    from local_ai_hub.http_server import Handler

    missing_root = _scan(tmp_path / "missing", "fn:needle")
    missing_pattern = _scan(tmp_path, "  ")
    assert (missing_root["success"], missing_root["status_code"]) == (False, 404)
    assert (missing_pattern["success"], missing_pattern["status_code"]) == (False, 400)

    denied = tmp_path / "external.php"
    denied.write_text("<?php function needle() {}\n", encoding="utf-8")
    symbolic = tmp_path / "alias.php"
    try:
        symbolic.symlink_to(denied)
    except (OSError, NotImplementedError):
        import pytest
        pytest.skip("symlinks unavailable on this platform")
    denied_result = _scan(tmp_path, "fn:needle", path="alias.php")
    assert (denied_result["success"], denied_result["status_code"]) == (False, 403)

    sent = []
    sender = SimpleNamespace(_send=lambda status, payload: sent.append((status, payload)))
    for payload, expected in (
        (denied_result, 403),
        (missing_root, 404),
        (missing_pattern, 400),
        ({"success": False, "status_code": 429}, 429),
        ({"success": False, "status_code": True}, 200),
        ({"success": False, "status_code": "403"}, 200),
        ({"success": False, "status_code": 999}, 200),
    ):
        Handler._send_service_result(sender, payload)
        assert sent[-1] == (expected, payload)


def test_structural_search_rejects_malformed_transport_fields_without_exceptions(tmp_path):
    source = tmp_path / "main.php"
    source.write_text("<?php function needle() {}\n", encoding="utf-8")
    for root in ("", "\x00", 12):
        result = _scan(root, "fn:needle")
        assert result["success"] is False
        assert result["status_code"] == 400
    for pattern in (None, 123, "a" * 513, "needle\x00"):
        result = _scan(tmp_path, pattern)
        assert result["success"] is False
        assert result["status_code"] == 400
    for path in (23, ["main.php"], "x" * 4097, "main.php\x00"):
        result = _scan(tmp_path, "fn:needle", path=path)
        assert result["success"] is False
        assert result["status_code"] == 400
