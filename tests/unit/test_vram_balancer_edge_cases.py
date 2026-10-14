from __future__ import annotations

import math
from typing import Any
import pytest

from local_ai_hub.vram_balancer import VRAMBalancer


def test_pin_model_rejects_empty_name_and_handles_nan_ttl() -> None:
    balancer = VRAMBalancer()

    with pytest.raises(ValueError, match="model_name cannot be empty"):
        balancer.pin_model("")

    with pytest.raises(ValueError, match="model_name cannot be empty"):
        balancer.pin_model("   ")

    with pytest.raises(ValueError, match="model_name cannot be empty"):
        balancer.pin_model(None)  # type: ignore[arg-type]

    # NaN and negative TTL should safely normalize to positive finite TTL without becoming NaN
    res_nan = balancer.pin_model("qwen-nan", ttl_seconds=float("nan"))
    assert res_nan["pinned"] is True
    assert res_nan["model"] == "qwen-nan"
    assert math.isfinite(balancer._pin_expires)
    assert balancer.get_pinned_model() == "qwen-nan"

    res_neg = balancer.pin_model("qwen-neg", ttl_seconds=-5.0)
    assert res_neg["pinned"] is True
    assert math.isfinite(balancer._pin_expires)
    assert balancer.get_pinned_model() == "qwen-neg"


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

    # None or non-dict input does not crash
    st_none = balancer._status_from_telemetry(None)  # type: ignore[arg-type]
    assert st_none["pressure_level"] == "nominal"
    assert st_none["available"] is False

    # String / invalid numbers in telemetry dict do not raise ValueError
    corrupt_gpu = {
        "available": True,
        "vram_total_mb": "invalid_number",
        "vram_used_mb": "N/A",
        "vram_used_pct": "not_a_float",
    }
    st_corrupt = balancer._status_from_telemetry(corrupt_gpu)
    assert st_corrupt["vram_total_mb"] == 0.0
    assert st_corrupt["vram_used_mb"] == 0.0
    assert st_corrupt["pressure_level"] == "nominal"


def test_recommended_context_budget_safe_conversion() -> None:
    balancer = VRAMBalancer()

    # Non-positive returns minimum clamp 4096
    assert balancer.recommended_context_budget(-1000) == 4096
    assert balancer.recommended_context_budget(0) == 4096

    # Non-numeric string gracefully falls back to default 32768
    assert balancer.recommended_context_budget("invalid") == 32768  # type: ignore[arg-type]


def test_config_safe_initialization() -> None:
    b1 = VRAMBalancer(None)
    assert isinstance(b1.config, dict)

    b2 = VRAMBalancer("not-a-dict")  # type: ignore[arg-type]
    assert isinstance(b2.config, dict)
