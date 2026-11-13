from __future__ import annotations

import time

import pytest

from local_ai_hub.vram_balancer import VRAMBalancer


def _balanced_sample(**overrides: object) -> dict[str, object]:
    sample: dict[str, object] = {
        "available": True,
        "vendor": "nvidia",
        "backend": "cuda",
        "gpu_name": "fixture GPU",
        "vram_total_mb": 8192.0,
        "vram_used_mb": 1024.0,
        "vram_used_pct": 12.5,
    }
    sample.update(overrides)
    return sample


def _assert_conservative_unknown(result: dict[str, object], reason: str) -> None:
    assert result["available"] is False
    assert result["pressure_level"] == "unknown"
    assert result["context_budget_factor"] <= 0.25
    assert result["throttle_background"] is True
    speculative = result["speculative_inference"]
    assert isinstance(speculative, dict)
    assert speculative["recommended"] is False
    assert speculative["runtime_active"] is None
    assert speculative["runtime_status"] == "unknown"
    assert result["telemetry_error"] == reason
    assert result["telemetry_wait_timed_out"] is False


def test_speculative_recommendation_is_separate_from_configuration_and_runtime() -> None:
    balancer = VRAMBalancer({"models": {"fast_code": "qwen2.5-coder:7b", "draft_code": "qwen2.5-coder:3b"}})
    result = balancer._status_from_telemetry(
        _balanced_sample(vram_used_mb=6000.0, vram_used_pct=73.2)
    )

    speculative = result["speculative_inference"]
    assert speculative["recommended"] is True
    assert speculative["configured"] is True
    assert speculative["pair_status"] == "valid"
    assert speculative["draft_size_billions"] == 3.0
    assert speculative["target_size_billions"] == 7.0
    assert speculative["runtime_active"] is None
    assert speculative["runtime_status"] == "unknown"


def test_successful_sample_reports_explicit_freshness_state() -> None:
    balancer = VRAMBalancer({})

    result = balancer._status_from_telemetry(_balanced_sample(timestamp=time.time()))

    assert result["telemetry_sampling"] is False
    assert result["telemetry_stale"] is False
    assert result["telemetry_wait_timed_out"] is False
    assert result["telemetry_error"] is None


@pytest.mark.parametrize(
    ("target", "draft", "expected_status"),
    [
        ("qwen2.5-coder:3b", "qwen2.5-coder:3b", "draft_not_smaller_than_target"),
        ("qwen2.5-coder:3b", "qwen2.5-coder:7b", "draft_not_smaller_than_target"),
        ("qwen2.5-coder:7b", "custom-model:latest", "model_size_unknown"),
    ],
)
def test_incompatible_or_unknown_speculative_pair_is_not_recommended(
    target: str, draft: str, expected_status: str
) -> None:
    balancer = VRAMBalancer({"models": {"fast_code": target, "draft_code": draft}})
    result = balancer._status_from_telemetry(
        _balanced_sample(vram_used_mb=6000.0, vram_used_pct=73.2)
    )

    speculative = result["speculative_inference"]
    assert speculative["configured"] is True
    assert speculative["recommended"] is False
    assert speculative["pair_status"] == expected_status
    assert speculative["runtime_active"] is None


def test_missing_explicit_speculative_pair_is_unconfigured() -> None:
    balancer = VRAMBalancer({"models": {"fast_code": "qwen2.5-coder:7b"}})
    result = balancer._status_from_telemetry(
        _balanced_sample(vram_used_mb=6000.0, vram_used_pct=73.2)
    )

    speculative = result["speculative_inference"]
    assert speculative["configured"] is False
    assert speculative["pair_status"] == "unconfigured"
    assert speculative["recommended"] is False


@pytest.mark.parametrize(
    "sample,reason",
    [
        ({"available": False}, "sample_unavailable"),
        ({"available": True, "vram_total_mb": 8192.0}, "sample_unavailable"),
        (_balanced_sample(vram_used_mb=None, vram_used_pct=None), "sample_unavailable"),
        (_balanced_sample(vram_used_mb=float("nan")), "sample_invalid"),
        (_balanced_sample(vram_used_pct=float("inf")), "sample_invalid"),
        (_balanced_sample(vram_used_pct=-1.0), "sample_invalid"),
        (_balanced_sample(vram_available_mb=float("nan")), "sample_invalid"),
        (_balanced_sample(vram_available_mb=-1.0), "sample_invalid"),
        (_balanced_sample(vram_available_mb=True), "sample_invalid"),
        (_balanced_sample(vram_available_mb=8193.0), "sample_invalid"),
        (_balanced_sample(vram_total_mb="8192"), "sample_invalid"),
        (_balanced_sample(vram_used_mb=9000.0), "sample_invalid"),
        ({"available": "false"}, "sample_invalid"),
    ],
)
def test_invalid_or_incomplete_sample_uses_conservative_unknown(
    sample: dict[str, object], reason: str
) -> None:
    balancer = VRAMBalancer({"token_budget": {"default_context": 32768}})
    result = balancer._status_from_telemetry(sample)
    _assert_conservative_unknown(result, reason)


def test_explicit_zero_percent_cannot_hide_measured_used_to_total_pressure() -> None:
    balancer = VRAMBalancer()
    result = balancer._status_from_telemetry(
        _balanced_sample(vram_total_mb=10000.0, vram_used_mb=9700.0, vram_used_pct=0.0)
    )
    assert result["pressure_level"] == "critical"
    assert result["context_budget_factor"] == 0.25
    assert result["throttle_background"] is True
    assert result["vram_used_mb"] == 9700.0
    assert result["vram_used_pct"] == 0.0
    assert result["policy_pressure_pct"] == 97.0
    assert result["policy_headroom_mb"] == 300.0
    assert result["policy_measurement_basis"] == "dedicated_observed"
    assert result["policy_pressure_is_derived"] is True
    assert result["speculative_inference"]["recommended"] is False
    assert result["speculative_inference"]["runtime_active"] is None


def test_free_vram_only_sample_derives_pressure_and_headroom() -> None:
    balancer = VRAMBalancer()
    result = balancer._status_from_telemetry(
        _balanced_sample(
            vram_used_mb=None,
            vram_used_pct=None,
            vram_available_mb=6144.0,
        )
    )

    assert result["available"] is True
    assert result["vram_used_mb"] is None
    assert result["vram_available_mb"] == 6144.0
    assert result["pressure_level"] == "nominal"
    assert result["context_budget_factor"] == 1.0
    assert result["throttle_background"] is False
    assert result["policy_pressure_pct"] == 25.0
    assert result["policy_headroom_mb"] == 6144.0
    assert result["policy_measurement_basis"] == "dedicated_observed"
    assert result["policy_pressure_is_derived"] is True


def test_valid_rocm_style_pressure_keeps_existing_thresholds() -> None:
    balancer = VRAMBalancer()
    result = balancer._status_from_telemetry(
        {
            "available": True,
            "vendor": "amd",
            "backend": "rocm",
            "live_metrics": True,
            "vram_total_mb": 10000.0,
            "vram_used_mb": 8700.0,
            "vram_used_pct": 87.0,
        }
    )
    assert result["pressure_level"] == "high"
    assert result["context_budget_factor"] == 0.5
    assert result["throttle_background"] is True


def test_integrated_unified_usage_can_be_assessed_when_measured() -> None:
    balancer = VRAMBalancer()
    result = balancer._status_from_telemetry(
        {
            "available": True,
            "vendor": "intel",
            "backend": "directml",
            "integrated": True,
            "shared_memory": True,
            "vram_total_mb": 0.0,
            "unified_memory_mb": 32768.0,
            "unified_memory_used_mb": 8192.0,
            "unified_memory_available_mb": 24576.0,
            "unified_memory_used_pct": 25.0,
        }
    )
    assert result["pressure_level"] == "nominal"
    assert result["context_budget_factor"] == 1.0
    assert result["vram_used_mb"] is None
    assert result["vram_used_pct"] is None
    assert result["policy_pressure_pct"] == 25.0
    assert result["policy_measurement_basis"] == "shared_unified_observed"


def test_integrated_dedicated_zero_does_not_measure_unified_pool() -> None:
    balancer = VRAMBalancer()
    result = balancer._status_from_telemetry(
        {
            "available": True,
            "vendor": "intel",
            "backend": "directml",
            "integrated": True,
            "unified_memory_mb": 32768.0,
            "vram_used_mb": 0.0,
            "vram_used_pct": 0.0,
        }
    )
    _assert_conservative_unknown(result, "sample_unavailable")


def test_integrated_and_windows_inventory_samples_without_headroom_are_unknown() -> None:
    balancer = VRAMBalancer()
    integrated = balancer._status_from_telemetry(
        {
            "available": True,
            "vendor": "intel",
            "backend": "directml",
            "integrated": True,
            "shared_memory": True,
            "vram_total_mb": 0.0,
            "reported_adapter_memory_mb": 256.0,
            "unified_memory_mb": 32768.0,
            "vram_used_mb": 0.0,
            "vram_used_pct": 0.0,
            "live_metrics": False,
        }
    )
    _assert_conservative_unknown(integrated, "sample_unavailable")

    windows_dedicated = balancer._status_from_telemetry(
        {
            "available": True,
            "vendor": "nvidia",
            "backend": "cuda",
            "vram_total_mb": 8192.0,
            "reported_adapter_memory_mb": 0.0,
            "vram_used_mb": 0.0,
            "vram_used_pct": 0.0,
            "live_metrics": True,
        }
    )
    _assert_conservative_unknown(windows_dedicated, "sample_unavailable")


def test_unknown_sample_keeps_fresh_pin_and_publishes_one_generation() -> None:
    balancer = VRAMBalancer()
    balancer._pinned_model = "warm-model"
    balancer._pin_expires = time.monotonic() + 60.0
    balancer._status_from_telemetry(_balanced_sample())
    generation_before = balancer._status_generation

    result = balancer._status_from_telemetry(_balanced_sample(vram_used_mb=None, vram_used_pct=None))

    assert balancer._status_generation == generation_before + 1
    assert result["pinned_model"]["model"] == "warm-model"
    _assert_conservative_unknown(result, "sample_unavailable")
