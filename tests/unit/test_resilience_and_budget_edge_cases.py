from __future__ import annotations

import math
from pathlib import Path
import pytest

from local_ai_hub.resilience import CircuitBreakerRegistry
from local_ai_hub.response_budget import _safe_limit, _bounded_string, is_valid_evidence_id


def test_circuit_breaker_edge_cases():
    # NaN, Inf, bool in constructor
    cb = CircuitBreakerRegistry(
        failure_threshold=float("nan"),  # type: ignore
        cooldown_seconds=float("inf"),  # type: ignore
        probe_timeout_seconds=True,  # type: ignore
    )
    assert cb.failure_threshold >= 1
    assert math.isfinite(cb.cooldown_seconds)
    assert math.isfinite(cb.probe_timeout_seconds)

    # Null bytes and None keys
    assert cb.is_allowed(None) is True  # type: ignore
    assert cb.is_open(None) is False  # type: ignore

    cb.failure("model\x00bad")
    cb.failure("model\x00bad")
    cb.failure("model\x00bad")
    assert cb.is_open("model\x00bad") is True
    assert cb.is_allowed("model\x00bad") is False

    # reset
    cb.reset("model\x00bad")
    assert cb.is_open("model\x00bad") is False

    cb.failure("m1")
    cb.failure("m2")
    cb.reset(None)
    assert len(cb.status()) == 0


def test_response_budget_safe_limit_and_evidence():
    # Boolean limit must fall back to default, not convert True -> 1
    assert _safe_limit(True, 1200) == 1200
    assert _safe_limit(False, 1200) == 1200

    # _bounded_string with boolean or negative max_chars
    assert _bounded_string("sample text", max_chars=True) == ""  # type: ignore
    assert _bounded_string("sample text", max_chars=-5) == ""

    # is_valid_evidence_id
    assert is_valid_evidence_id("E0123456789abcdef0123") is True
    assert is_valid_evidence_id("E0123456789ABCDEF0123") is True
    assert is_valid_evidence_id(None) is False
    assert is_valid_evidence_id(True) is False
    assert is_valid_evidence_id("E0123") is False
    assert is_valid_evidence_id("E0123456789abcdef0123\x00") is False
    assert is_valid_evidence_id("invalid_id") is False
