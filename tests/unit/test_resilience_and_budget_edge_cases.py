from __future__ import annotations

import math
from pathlib import Path
import pytest

from local_ai_hub.resilience import CircuitBreakerRegistry
from local_ai_hub.response_budget import _safe_limit, _bounded_string, is_valid_evidence_id


def test_circuit_breaker_edge_cases():
    for kwargs in ({"failure_threshold": float("nan")}, {"cooldown_seconds": float("inf")}, {"probe_timeout_seconds": True}):
        with pytest.raises(ValueError):
            CircuitBreakerRegistry(**kwargs)
    cb = CircuitBreakerRegistry()
    for key in (None, "model\x00bad"):
        with pytest.raises(ValueError):
            cb.allow(key)
        with pytest.raises(ValueError):
            cb.failure(key)
    assert cb.allow("model") is True
    for _ in range(3):
        cb.failure("model")
    assert cb.status()["model"]["open"] is True
    assert cb.allow("model") is False
    cb.success("model")
    assert cb.allow("model") is True


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
