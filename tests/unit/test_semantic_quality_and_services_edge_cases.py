from __future__ import annotations

import pytest

from local_ai_hub import semantic_quality
from local_ai_hub.services import (
    enclosing_symbol_at_line,
    _split_review_diff,
    cache_decision_reason,
    _redact_guard_reason,
)


def test_semantic_quality_edge_cases():
    # Task with null byte
    res_task = semantic_quality.assess_semantic_result("task\x00bad", ["src/a.py"], "valid output")
    assert res_task["usable"] is False
    assert res_task["reason"] == "malformed_task"

    # Evidence paths with null byte
    res_path = semantic_quality.assess_semantic_result("task a", ["src/a\x00bad.py"], "valid output")
    assert res_path["usable"] is False
    assert res_path["reason"] == "unsafe_path"

    # Evidence paths with path traversal
    res_trav = semantic_quality.assess_semantic_result("task a", ["../src/a.py"], "valid output")
    assert res_trav["usable"] is False
    assert res_trav["reason"] == "unsafe_path"

    # Helper functions
    assert semantic_quality.is_usable({"usable": True}) is True
    assert semantic_quality.is_usable({"usable": False}) is False
    assert semantic_quality.is_usable({}) is False

    assert semantic_quality.is_valid_task("valid task") is True
    assert semantic_quality.is_valid_task("task\x00bad") is False
    assert semantic_quality.is_valid_task("") is False
    assert semantic_quality.is_valid_task(None) is False

    norm_paths = semantic_quality.normalize_evidence_paths(["src/a.py", "src/b.py"])
    assert norm_paths == ("src/a.py", "src/b.py")
    assert semantic_quality.normalize_evidence_paths(["bad\x00path"]) is None


def test_services_helper_edge_cases():
    # enclosing_symbol_at_line with null byte path or NaN line
    assert enclosing_symbol_at_line("def foo(): pass", "foo\x00.py", 1) is None
    assert enclosing_symbol_at_line("def foo(): pass", "foo.py", float("nan")) is None  # type: ignore
    assert enclosing_symbol_at_line("def foo(): pass", "foo.py", -5) is None
    assert enclosing_symbol_at_line(None, "foo.py", 1) is None  # type: ignore

    # _split_review_diff with NaN / Inf / bool max_tokens
    assert _split_review_diff(None, 1000) == []  # type: ignore
    assert _split_review_diff("", 1000) == []

    diff_sample = "diff --git a/file.py b/file.py\n@@ -1,2 +1,2 @@\n-old\n+new\n"
    chunks_nan = _split_review_diff(diff_sample, float("nan"))  # type: ignore
    assert len(chunks_nan) == 1

    chunks_inf = _split_review_diff(diff_sample, float("inf"))  # type: ignore
    assert len(chunks_inf) == 1

    # cache_decision_reason with None or whitespace
    assert cache_decision_reason(None, semantic_query=None) == "exact_reuse"  # type: ignore
    assert cache_decision_reason("  SEMANTIC  ", semantic_query="q") == "semantic_reuse"
    assert cache_decision_reason("ollama", semantic_query="   ") == "new_exact_key"

    # _redact_guard_reason with null bytes
    redacted = _redact_guard_reason("reason with \x00 null bytes and token: secret123")
    assert "\x00" not in redacted
    assert "secret123" not in redacted
