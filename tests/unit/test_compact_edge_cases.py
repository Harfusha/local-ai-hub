from __future__ import annotations

import math
import json
from typing import Any

import pytest

from local_ai_hub.compact import (
    compact_result,
    is_compacted,
    omitted_counts,
    syntax_aware_truncate,
)


def test_syntax_aware_truncate_non_positive_and_tight_caps() -> None:
    text = "hello world\x00 test string"
    # Null bytes stripped
    # max_chars <= 0 returns ""
    assert syntax_aware_truncate(text, 0) == ""
    assert syntax_aware_truncate(text, -10) == ""

    # max_chars < len(marker) returns text[:max_chars]
    marker = "\n[... compact MCP projection ...]"
    assert len(marker) == 33
    tight = syntax_aware_truncate("abcdefghijklmnop", 5)
    assert tight == "abcde"

    # With null bytes
    assert syntax_aware_truncate("foo\x00bar\x00baz", 6) == "foobar"


def test_syntax_aware_truncate_defensive_types() -> None:
    # Non-string passes through
    assert syntax_aware_truncate(12345, 10) == 12345  # type: ignore
    assert syntax_aware_truncate(None, 10) is None  # type: ignore

    # Non-integer / NaN max_chars
    assert syntax_aware_truncate("hello world", float("nan")) == ""  # type: ignore
    assert syntax_aware_truncate("hello world", "invalid") == ""  # type: ignore


def test_compact_result_clamps_negative_and_small_limits() -> None:
    data = {
        "text": "x" * 200,
        "evidence": ["e1", "e2", "e3"],
        "results": [{"a": 1}, {"b": 2}],
    }
    # max_text_chars clamped to >= 64, max_evidence/max_items clamped to >= 0
    res = compact_result(data, max_text_chars=10, max_evidence=-5, max_items=-2)
    assert len(res["text"]) <= 120
    assert res["evidence"] == []
    assert res["evidence_omitted"] == 3
    assert res["results"] == []
    assert res["results_omitted"] == 2


@pytest.mark.parametrize("artifact_id", [None, "artifact-real-123"])
def test_compact_result_preserves_final_test_summary_and_real_artifact_pointer(artifact_id: str | None) -> None:
    final_summary = "=== 59 passed, 3 skipped in 120.34s ==="
    summary = "\n".join(["SKIPPED slow platform case: " + "x" * 220 for _ in range(20)] + [final_summary])
    data: dict[str, Any] = {"summary": summary, "output_truncated": True}
    if artifact_id is not None:
        data["output_artifact_id"] = artifact_id

    compacted = compact_result(data, max_text_chars=128)

    assert len(compacted["summary"]) <= 128
    assert final_summary in compacted["summary"]
    assert "summary middle omitted" in compacted["summary"]
    if artifact_id is None:
        assert "output_artifact_id" not in compacted
    else:
        assert compacted["output_artifact_id"] == artifact_id


def test_compact_result_keeps_test_counts_and_elapsed_ends_when_summary_line_is_long() -> None:
    final_line = "=== 59 passed, 3 skipped " + "x" * 220 + " in 120.34s ==="

    compacted = compact_result({"summary": final_line}, max_text_chars=128)

    assert len(compacted["summary"]) <= 128
    assert compacted["summary"].startswith("=== 59 passed, 3 skipped")
    assert compacted["summary"].endswith("in 120.34s ===")
    assert " … " in compacted["summary"]


def test_compact_result_single_string_extra_fields() -> None:
    data = {
        "text": "hello",
        "job_id": "job-1234",
        "load_duration_ns": 9999,
    }
    # Single string instead of iterable of strings
    res = compact_result(data, extra_fields="job_id")
    assert res["job_id"] == "job-1234"
    assert "load_duration_ns" not in res


def test_compact_result_cycle_detection_and_depth_guard() -> None:
    # Cyclic dict
    d: dict[str, Any] = {"name": "cyclic"}
    d["self"] = d
    res = compact_result(d)
    assert res["name"] == "cyclic"
    assert res["self"] == "<cycle>"
    json.dumps(res)

    # Cyclic list
    l: list[Any] = ["item1"]
    l.append(l)
    res_l = compact_result(l)
    assert res_l[0] == "item1"
    assert res_l[1] == "<cycle>"
    json.dumps(res_l)

    # Deep nesting > 10 levels
    deep: dict[str, Any] = {"depth": 0}
    curr = deep
    for i in range(1, 15):
        nxt: dict[str, Any] = {"depth": i}
        curr["child"] = nxt
        curr = nxt
    res_deep = compact_result(deep)
    assert res_deep["depth"] == 0


def test_is_compacted_and_omitted_counts() -> None:
    clean = {"text": "short text", "evidence": [1, 2]}
    assert not is_compacted(clean)
    assert omitted_counts(clean) == {}

    compacted_dict = {
        "text": "short",
        "output_truncated": True,
        "evidence_omitted": 5,
        "results_omitted": 10,
        "repo_context": {"evidence_omitted": 3},
    }
    assert is_compacted(compacted_dict)
    assert omitted_counts(compacted_dict) == {
        "evidence": 5,
        "results": 10,
        "repo_evidence": 3,
    }

    # Text marker detection
    text_compacted = {"text": "hello\n[... compact MCP projection ...]"}
    assert is_compacted(text_compacted)

    # List of items
    assert is_compacted([clean, compacted_dict])
    assert not is_compacted([clean, {"val": 123}])
