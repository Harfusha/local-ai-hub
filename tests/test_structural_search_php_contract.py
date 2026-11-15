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
