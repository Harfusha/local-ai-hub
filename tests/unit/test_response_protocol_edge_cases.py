from __future__ import annotations

import math
import pytest

from local_ai_hub.response_protocol import (
    _dense,
    is_profile_supported,
    profile_fields,
    project_response,
    supported_profiles,
)


def test_dense_null_bytes_and_non_positive_limit() -> None:
    assert _dense("hello\x00world", 50) == "helloworld"
    assert _dense("hello", 0) == ""
    assert _dense("hello", -5) == ""
    assert _dense(None, 10) == ""  # type: ignore[arg-type]


def test_project_response_string_return_fields() -> None:
    payload = {
        "success": True,
        "status": "completed",
        "summary": "Specific test summary",
        "extra_verbose": "should not be included",
    }
    # Passing single string instead of tuple/list must not iterate characters
    res = project_response(payload, return_fields="summary")
    assert "summary" in res
    assert res["summary"] == "Specific test summary"
    assert "extra_verbose" not in res


def test_project_response_nan_inf_max_output_tokens() -> None:
    payload = {"success": True, "status": "ok", "summary": "test summary"}
    # NaN and Inf token budgets must not crash with ValueError
    res1 = project_response(payload, max_output_tokens=float("nan"))  # type: ignore[arg-type]
    assert res1["success"] is True

    res2 = project_response(payload, max_output_tokens=float("inf"))  # type: ignore[arg-type]
    assert res2["success"] is True

    res3 = project_response(payload, max_output_tokens=-100)
    assert res3["success"] is True


def test_response_protocol_inspection_helpers() -> None:
    profiles = supported_profiles()
    assert "minimal" in profiles
    assert "compact" in profiles
    assert "standard" in profiles
    assert "debug" in profiles

    assert is_profile_supported("compact") is True
    assert is_profile_supported("minimal") is True
    assert is_profile_supported("unknown_profile") is False
    assert is_profile_supported(None) is False  # type: ignore[arg-type]

    minimal_fields = profile_fields("minimal")
    assert minimal_fields is not None
    assert "success" in minimal_fields
    assert "status" in minimal_fields
    assert "steps" not in minimal_fields

    assert profile_fields("debug") is None
    assert profile_fields("unknown") is None
