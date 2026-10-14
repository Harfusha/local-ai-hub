from __future__ import annotations

import pytest

from local_ai_hub.prompt_contracts import (
    _clip,
    _lines,
    build_prompt,
    can_model_perform,
    capability_for,
    get_model_tier,
    is_operation_supported,
    supported_operations,
)


def test_clip_null_bytes_and_non_positive_limit() -> None:
    assert _clip("hello\x00world", 50) == "helloworld"
    assert _clip("hello", 0) == ""
    assert _clip("hello", -5) == ""
    assert _clip(None, 10) == ""  # type: ignore[arg-type]


def test_lines_defensive_non_iterable_and_null_bytes() -> None:
    assert _lines(None) == "- none supplied"  # type: ignore[arg-type]
    assert _lines(12345) == "- none supplied"  # type: ignore[arg-type]
    res = _lines(["item\x00one", "item\r\ntwo"])
    assert "\x00" not in res
    assert "itemone" in res


def test_build_prompt_with_none_iterables() -> None:
    package = build_prompt(
        operation="delegate",
        model="qwen2.5-coder:7b",
        task="Test task with None iterables",
        acceptance_criteria=None,  # type: ignore[arg-type]
        evidence_ids=None,  # type: ignore[arg-type]
        changed_paths=None,  # type: ignore[arg-type]
    )
    assert package.operation == "delegate"
    assert "- none supplied" in package.user


def test_large_model_tier_support() -> None:
    c72b = capability_for("qwen2.5-coder:72b")
    assert c72b.tier == "heavy"

    c70b = capability_for("llama-3.1-70b")
    assert c70b.tier == "heavy"


def test_prompt_contracts_inspection_helpers() -> None:
    ops = supported_operations()
    assert "delegate" in ops
    assert "review_diff" in ops
    assert "explore" in ops

    assert is_operation_supported("review_diff") is True
    assert is_operation_supported("delegate") is True
    assert is_operation_supported("nonexistent_op") is False
    assert is_operation_supported(None) is False  # type: ignore[arg-type]

    assert get_model_tier("qwen2.5-coder:7b") == "reasoning"
    assert get_model_tier("qwen2.5-coder:1.5b") == "preprocessing"

    assert can_model_perform("qwen2.5-coder:7b", "root_cause") is True
    assert can_model_perform("qwen2.5-coder:7b", "apply_changes") is False
    assert can_model_perform(None, "root_cause") is False  # type: ignore[arg-type]
