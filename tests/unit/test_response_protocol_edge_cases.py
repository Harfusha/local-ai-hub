from __future__ import annotations

import json
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


def test_project_response_rejects_unfit_final_envelope() -> None:
    payload = {
        "success": True,
        "status": "completed",
        "work_id": "w" * 200,
        "task_id": "t" * 200,
        "error": "e" * 200,
        "needs_agent": True,
        "handoff_id": "h" * 200,
        "artifact_id": "a" * 200,
        "requires_primary_review": True,
        "outcome_unknown": True,
        "timed_out": True,
        "in_progress": True,
        "local_exploration_status": "x" * 200,
        "rollback_status": "r" * 200,
        "task_barrier_status": "b" * 200,
        "task_barrier_error": "z" * 200,
    }
    result = project_response(payload, profile="debug", max_output_tokens=64)
    wire = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    assert len(wire) <= 64 * 4
    assert result["success"] is False
    assert result["status"] == "response_budget_exceeded"
    assert result["budget_rejected"] is True


def test_project_response_enforces_utf8_serialized_byte_budget() -> None:
    result = project_response(
        {"success": True, "status": "ok", "error": "é" * 150},
        profile="debug",
        max_output_tokens=64,
    )
    wire = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    assert len(wire) <= 64 * 4
    assert result.get("truncated") is True or result.get("status") == "response_budget_exceeded"


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
