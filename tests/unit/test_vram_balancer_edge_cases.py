"""Deferred source integration regressions; no GPU sampling or model calls."""
from __future__ import annotations

import pytest

from local_ai_hub.vram_balancer import VRAMBalancer


@pytest.mark.parametrize("model,ttl", [
    ("", 1), ("  ", 1), (None, 1), ("fake", 0), ("fake", -1), ("fake", True),
    ("fake", float("nan")), ("fake", float("inf")), ("fake", None),
])
def test_invalid_pin_inputs_preserve_existing_pin(model, ttl):
    balancer = VRAMBalancer()
    balancer.pin_model("existing", 10)
    before = (balancer._pinned_model, balancer._pin_expires, balancer._status_generation)
    with pytest.raises(ValueError):
        balancer.pin_model(model, ttl)
    assert (balancer._pinned_model, balancer._pin_expires, balancer._status_generation) == before


@pytest.mark.parametrize("base", [64, 1024, 2048, 4096, 8192, 32768])
@pytest.mark.parametrize("factor", [0, 0.25, 0.5, 1, 2, -1, float("nan"), float("inf"), None, "invalid"])
def test_context_recommendation_never_exceeds_requested_window(monkeypatch, base, factor):
    balancer = VRAMBalancer()
    monkeypatch.setattr(balancer, "status", lambda: {"context_budget_factor": factor})
    assert 1 <= balancer.recommended_context_budget(base) <= base


@pytest.mark.parametrize("base", [0, -1, True, "4096", 1.5])
def test_invalid_context_request_fails_before_hardware_sampling(monkeypatch, base):
    balancer = VRAMBalancer()
    monkeypatch.setattr(balancer, "status", lambda: pytest.fail("invalid request sampled GPU"))
    with pytest.raises(ValueError):
        balancer.recommended_context_budget(base)
def test_is_model_pinned_and_pinned_model_info() -> None:
    balancer = VRAMBalancer()

    assert balancer.is_model_pinned("qwen:1.5b") is False
    assert balancer.pinned_model_info() is None

    balancer.pin_model("qwen:1.5b", ttl_seconds=120.0)
    assert balancer.is_model_pinned("qwen:1.5b") is True
    assert balancer.is_model_pinned("  qwen:1.5b  ") is True
    assert balancer.is_model_pinned("other-model") is False

    info = balancer.pinned_model_info()
    assert info is not None
    assert info["model"] == "qwen:1.5b"
    assert info["ttl_remaining_seconds"] > 0

    balancer.unpin_model()
    assert balancer.is_model_pinned("qwen:1.5b") is False
    assert balancer.pinned_model_info() is None


def test_telemetry_safe_parsing_resilience() -> None:
    balancer = VRAMBalancer()

    # Invalid telemetry fails closed without claiming a healthy sample.
    st_none = balancer._status_from_telemetry(None)  # type: ignore[arg-type]
    assert st_none["pressure_level"] == "unknown"
    assert st_none["available"] is False
    assert st_none["telemetry_error"] == "sample_invalid"

    # String / invalid numbers in telemetry dict do not raise ValueError
    corrupt_gpu = {
        "available": True,
        "vram_total_mb": "invalid_number",
        "vram_used_mb": "N/A",
        "vram_used_pct": "not_a_float",
    }
    st_corrupt = balancer._status_from_telemetry(corrupt_gpu)
    assert st_corrupt["available"] is False
    assert st_corrupt["pressure_level"] == "unknown"
    assert st_corrupt["telemetry_error"] == "sample_invalid"


def test_config_safe_initialization() -> None:
    b1 = VRAMBalancer(None)
    assert isinstance(b1.config, dict)

    b2 = VRAMBalancer("not-a-dict")  # type: ignore[arg-type]
    assert isinstance(b2.config, dict)
