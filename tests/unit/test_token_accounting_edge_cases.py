from __future__ import annotations

import math
from pathlib import Path

import pytest

from local_ai_hub.token_accounting import (
    SavingsSignals,
    _safe_metadata_float,
    _safe_metadata_text,
    finalize_tool_accounting,
    token_efficiency_metadata,
    tool_request_tokens,
)


def test_safe_metadata_float_nan_inf_poison_prevention() -> None:
    assert _safe_metadata_float(float("nan")) == 0.0
    assert _safe_metadata_float(float("inf")) == 0.0
    assert _safe_metadata_float(float("-inf")) == 0.0
    assert _safe_metadata_float(-50.5) == 0.0
    assert _safe_metadata_float("nan") == 0.0
    assert _safe_metadata_float("inf") == 0.0
    assert _safe_metadata_float(45.67) == 45.7
    assert _safe_metadata_float(None) == 0.0


def test_safe_metadata_text_null_byte_prevention() -> None:
    sanitized = _safe_metadata_text("task\x00poison\r\nline2")
    assert "\x00" not in sanitized
    assert "\r" not in sanitized
    assert "\n" not in sanitized
    assert "taskpoison line2" == sanitized


def test_token_efficiency_metadata_malformed_input() -> None:
    # Non-mapping metadata should not crash with TypeError or ValueError
    m1 = token_efficiency_metadata(None)
    assert isinstance(m1, dict)
    assert m1["queue_wait_ms"] == 0.0

    m2 = token_efficiency_metadata("invalid-string")  # type: ignore[arg-type]
    assert isinstance(m2, dict)

    m3 = token_efficiency_metadata(12345)  # type: ignore[arg-type]
    assert isinstance(m3, dict)

    # NaN queue_wait_ms is safely sanitized to 0.0
    m4 = token_efficiency_metadata({"queue_wait_ms": float("nan")})
    assert m4["queue_wait_ms"] == 0.0
    assert math.isfinite(m4["queue_wait_ms"])


def test_tool_request_tokens_malformed_arguments() -> None:
    # Malformed arguments should not raise TypeError
    tok1 = tool_request_tokens("local_ai_repo", None)  # type: ignore[arg-type]
    assert tok1 > 0

    tok2 = tool_request_tokens("local_ai_repo", "not-a-mapping")  # type: ignore[arg-type]
    assert tok2 > 0


def test_savings_signals_has_signals_and_clear() -> None:
    signals = SavingsSignals()
    assert signals.has_signals() is False

    signals.add_input("source-1", 100)
    assert signals.has_signals() is True

    signals.clear()
    assert signals.has_signals() is False
    assert signals.summary()["gross_cloud_tokens_avoided_est"] == 0


def test_finalize_tool_accounting_malformed_arguments() -> None:
    acc = finalize_tool_accounting(
        tool_name="local_ai_repo",
        arguments=None,  # type: ignore[arg-type]
        response={"success": True},
    )
    assert isinstance(acc, dict)
    assert acc["tool"] == "local_ai_repo"
    assert "gross_cloud_tokens_avoided_est" in acc
