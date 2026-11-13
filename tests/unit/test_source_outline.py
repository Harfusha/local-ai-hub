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

