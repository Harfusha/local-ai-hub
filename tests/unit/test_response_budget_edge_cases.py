from __future__ import annotations

import math

import pytest

from local_ai_hub.response_budget import (
    _safe_limit,
    budget_response,
    delta_response,
    get_response_budget_info,
    get_returned_tokens,
    is_budget_rejected,
    is_response_budgeted,
)


def test_safe_limit_non_finite_and_negative() -> None:
    assert _safe_limit(float("nan"), 1200) == 1200
    assert _safe_limit(float("inf"), 1200) == 1200
    assert _safe_limit(float("-inf"), 1200) == 1200
    assert _safe_limit(-100, 1200) == 1200
    assert _safe_limit(0, 1200) == 1200
    assert _safe_limit(500, 1200) == 500
    assert _safe_limit(None, 1200) == 1200
    assert _safe_limit("not-a-number", 1200) == 1200


def test_delta_response_null_byte_and_non_mapping() -> None:
    d1 = delta_response(None, {"key": "val"}, result_id="res\x00poison")
    assert "\x00" not in d1["result_id"]
    assert d1["result_id"] == "respoison"

    d2 = delta_response("str1", "str2", result_id=None)  # type: ignore[arg-type]
    assert d2["result_id"] == ""
    assert isinstance(d2["delta"], dict)


def test_budget_response_primitive_values() -> None:
    # When payload exceeds budget, response_budget is attached
    large_payload = {"data": "x" * 2000}
    res1 = budget_response(large_payload, max_tokens=128)
    assert is_response_budgeted(res1) is True
    assert get_returned_tokens(res1) <= 128

    # When token_metadata is passed, response_budget is attached even for small payloads
    res2 = budget_response({"data": "small"}, max_tokens=250, token_metadata={"task_id": "t1"})
    assert is_response_budgeted(res2) is True
    assert get_returned_tokens(res2) <= 250

    # Primitive string directly returns as-is
    res3 = budget_response("simple string payload", max_tokens=250)
    assert res3 == "simple string payload"


def test_response_budget_inspection_helpers() -> None:
    valid_res = {"success": True, "data": "test", "response_budget": {"requested_tokens": 100, "returned_tokens": 42}}
    assert is_response_budgeted(valid_res) is True
    assert get_response_budget_info(valid_res) == {"requested_tokens": 100, "returned_tokens": 42}
    assert get_returned_tokens(valid_res) == 42
    assert is_budget_rejected(valid_res) is False

    rejected_res = {"success": False, "response_budget": {"requested_tokens": 100, "returned_tokens": 30, "rejected": True}}
    assert is_budget_rejected(rejected_res) is True

    # Non-budgeted or None inputs
    assert is_response_budgeted(None) is False
    assert is_response_budgeted({}) is False
    assert get_response_budget_info(None) is None
    assert get_returned_tokens(None) == 0
    assert is_budget_rejected(None) is False
