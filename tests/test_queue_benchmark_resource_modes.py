"""Admission evidence must describe the sample that made this decision."""

from types import SimpleNamespace

import pytest

from local_ai_hub.async_jobs import AsyncJobManager


@pytest.mark.parametrize("pressure,throttle,factor,state,retryable", [
    ("nominal", False, 1.0, "accepted", False),
    ("moderate", False, 1.0, "degraded", False),
    ("high", False, 1.0, "degraded", False),
    ("unknown", False, 0.25, "degraded", False),
    ("high", True, 0.5, "rejected", True),
    ("critical", False, 0.25, "rejected", True),
])
def test_admission_keeps_same_sample_and_policy(pressure, throttle, factor, state, retryable):
    calls = []

    def provider():
        calls.append(True)
        return {"available": True, "pressure_level": pressure, "throttle_background": throttle,
                "context_budget_factor": factor, "vram_used_pct": 92.0,
                "sample_timestamp": 123.0, "api_token": "never-copy-this"}

    manager = object.__new__(AsyncJobManager)
    manager.scheduler = SimpleNamespace(resource_status=provider)
    result = manager._resource_admission()
    assert result["state"] == state
    assert result["retryable"] is retryable
    sample = result["resource_sample"]
    assert sample["pressure_level"] == pressure
    assert sample["throttle_background"] is throttle
    assert sample["context_budget_factor"] == factor
    assert sample["sample_timestamp"] == 123.0
    assert sample["measured_basis"]["vram_used_pct"] == 92.0
    assert sample["measured_basis"]["vram_total_mb"] is None
    assert sample["provider"].endswith("provider")
    assert "never-copy-this" not in str(result)
    assert calls == [True]


def test_unknown_fallback_zero_is_not_measured_capacity():
    manager = object.__new__(AsyncJobManager)
    manager.scheduler = SimpleNamespace(resource_status=lambda: {
        "available": False, "pressure_level": "unknown", "context_budget_factor": 0.25,
        "vram_total_mb": 0, "vram_used_pct": 0,
    })
    result = manager._resource_admission()
    assert result["state"] == "degraded"
    assert result["resource_sample"]["available"] is False
    assert all(value is None for value in result["resource_sample"]["measured_basis"].values())
