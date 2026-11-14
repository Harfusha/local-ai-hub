from pathlib import Path

from local_ai_hub.source_outline import ast_outline, fold_brace_blocks


def test_ast_outline_collapses_python_bodies(tmp_path):
    source = tmp_path / "example.py"
    source.write_text(
        "class Greeter:\n"
        "    def greet(self):\n"
        "        private_detail = 1\n"
        "        return private_detail\n",
        encoding="utf-8",
    )

    result = ast_outline(str(tmp_path), "example.py")

    assert result["success"] is True
    assert "class Greeter:" in result["outline"]
    assert "def greet" in result["outline"]
    assert "..." in result["outline"]
    assert "private_detail" not in result["outline"]


def test_ast_outline_keeps_root_confinement(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("private_detail = 1\n", encoding="utf-8")

    result = ast_outline(str(root), "../outside.py")

    assert result == {"success": False, "error": "file is outside project root"}


def test_ast_outline_reports_source_read_failure(tmp_path, monkeypatch):
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")
    original_read_text = Path.read_text

    def fail_target_read(path, *args, **kwargs):
        if path == source:
            raise OSError("access denied")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_target_read)

    result = ast_outline(str(tmp_path), "example.py")

    assert result == {
        "success": False,
        "error": "unable to read source file",
        "error_code": "source_read_error",
    }


def test_ast_outline_uses_brace_language_fallback(tmp_path):
    source = tmp_path / "example.js"
    source.write_text("function calculate() {\n  return 42;\n}\n", encoding="utf-8")

    result = ast_outline(str(tmp_path), "example.js")

    assert result["success"] is True
    assert result["polyglot"] is True
    assert "function calculate() {" in result["outline"]
    assert "return 42" not in result["outline"]


def test_fold_brace_blocks_can_preserve_target_symbols():
    folded = fold_brace_blocks(
        "function calculate() {\n  return 42;\n}\n", {"calculate"}
    )

    assert "return 42" in folded


def test_fold_brace_blocks_handles_strings_comments_and_templates():
    source = (
        "function complexMethod() {\n"
        '    const a = "}";\n'
        "    const b = '};';\n"
        "    const c = `template ${x + '}'} text`;\n"
        "    /* block comment with } */\n"
        "    // line comment with }\n"
        "    const regex = /\\/}/g;\n"
        "    return a;\n"
        "}\n"
    )
    folded = fold_brace_blocks(source)
    assert "function complexMethod() {" in folded
    assert "/* ... */" in folded
    assert "const a" not in folded
    assert "return a" not in folded


def test_fold_brace_blocks_handles_php_heredoc():
    source = (
        "function renderTemplate() {\n"
        "    $html = <<<EOD\n"
        "    <div class='test'>}</div>\n"
        "EOD;\n"
        "    return $html;\n"
        "}\n"
    )
    folded = fold_brace_blocks(source)
    assert "function renderTemplate() {" in folded
    assert "/* ... */" in folded
    assert "<div" not in folded


def test_fold_brace_blocks_handles_typescript_generics():
    source = (
        "function processItem<T extends { id: string }>(item: T): void {\n"
        "    const secret = item.id;\n"
        "    return;\n"
        "}\n"
    )
    folded = fold_brace_blocks(source)
    assert "function processItem<T extends { id: string }>(item: T): void {" in folded
    assert "/* ... */" in folded
    assert "const secret" not in folded


def test_fold_brace_blocks_handles_one_liners():
    source = "function oneLiner() { return 42; }\n"
    folded = fold_brace_blocks(source)
    assert "function oneLiner() { /* ... */ }" in folded


def test_ast_outline_bounded_large_file(tmp_path):
    source = tmp_path / "huge.js"
    # Create file larger than budget
    content = "function a() {\n    return 1;\n}\n" * 2000
    source.write_text(content, encoding="utf-8")
    file_size = source.stat().st_size
    assert file_size > 10000

    # Call with max_source_bytes = 4096
    result = ast_outline(str(tmp_path), "huge.js", max_source_bytes=4096)
    assert result["success"] is True
    assert result.get("truncated") is True
    assert result.get("partial") is False
    assert result.get("fallback_type") == "truncated_head"
    assert "suggested_slice" in result
    assert result["suggested_slice"]["start_line"] == 1
    assert result["suggested_slice"]["end_line"] > 1


def test_ast_outline_zero_byte_file(tmp_path):
    source = tmp_path / "empty.py"
    source.write_text("", encoding="utf-8")
    result = ast_outline(str(tmp_path), "empty.py")
    assert result["success"] is True
    assert result["outline"] == ""
    assert result["original_chars"] == 0
    assert result["outline_chars"] == 0


def test_ast_outline_binary_file_rejected(tmp_path):
    source = tmp_path / "binary.bin"
    source.write_bytes(b"\x00\x01\x02\x03\x04\x05")
    result = ast_outline(str(tmp_path), "binary.bin")
    assert result["success"] is False
    assert result["error_code"] == "binary_file"


