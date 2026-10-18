from __future__ import annotations

import json

from local_ai_hub.compact import compact_result, syntax_aware_truncate


def test_syntax_aware_truncate_line_boundary():
    sample = "line 1\nline 2\nline 3\nline 4\nline 5\nline 6\nline 7\nline 8"
    truncated = syntax_aware_truncate(sample, 40)
    # Shouldn't cut mid-word, should cut at a clean line
    lines = truncated.splitlines()
    assert lines[0] == "line 1"
    assert lines[1] == "line 2"


def test_syntax_aware_truncate_json():
    json_text = '{\n  "key1": "value1",\n  "key2": "value2",\n  "key3": "value3"\n}'
    truncated = syntax_aware_truncate(json_text, 35)
    # Should safely close bracket
    assert truncated.strip().endswith("}")


def test_syntax_aware_truncate_json_keeps_only_leading_properties():
    source = json.dumps({"first": "ok", "oversized": "x" * 80, "later": "must not leapfrog"})
    truncated = syntax_aware_truncate(source, 24)
    assert json.loads(truncated) == {"first": "ok"}


def test_syntax_aware_truncate_deep_json_falls_back_within_limit():
    source = "[" * 1100 + "0" + "]" * 1100
    truncated = syntax_aware_truncate(source, 80)
    assert len(truncated) <= 80


def test_compact_result_preserves_error_distillation():
    raw = {
        "text": "a" * 3000,
        "error_distillation": "test_foo:42: AssertionError",
    }
    res = compact_result(raw, max_text_chars=500)
    assert len(res["text"]) <= 600
    assert res["error_distillation"] == "test_foo:42: AssertionError"
