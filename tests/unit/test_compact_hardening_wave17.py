import pytest
from local_ai_hub.compact import compact_result, omitted_counts, syntax_aware_truncate


def test_compact_result_overflow_and_boolean_limits():
    payload = {
        "text": "sample text",
        "evidence": [{"evidence_id": "ev1"}, {"evidence_id": "ev2"}],
        "results": [{"item": 1}, {"item": 2}],
    }
    # Passing float('inf') must not raise unhandled OverflowError
    res = compact_result(
        payload,
        max_text_chars=float("inf"),
        max_evidence=float("inf"),
        max_items=float("inf"),
    )
    assert isinstance(res, dict)
    assert res["text"] == "sample text"

    # Passing booleans must use safe defaults, not True == 1
    res2 = compact_result(payload, max_evidence=True, max_items=True)
    assert len(res2["evidence"]) == 2
    assert len(res2["results"]) == 2


def test_compact_result_invalid_extra_fields():
    payload = {"text": "hello", "job_id": "123"}
    # extra_fields = True or 123 must not raise TypeError: object is not iterable
    res = compact_result(payload, extra_fields=True)
    assert isinstance(res, dict)
    assert res["text"] == "hello"

    res2 = compact_result(payload, extra_fields=123)
    assert isinstance(res2, dict)
    assert res2["text"] == "hello"


def test_omitted_counts_boolean_guard():
    # Booleans in evidence_omitted must not be treated as int
    data = {"evidence_omitted": True, "results_omitted": False}
    counts = omitted_counts(data)
    assert "evidence" not in counts
    assert "results" not in counts
