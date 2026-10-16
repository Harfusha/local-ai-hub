from __future__ import annotations

import pytest

from local_ai_hub.model_quality import (
    CandidateRegistry,
    aggregate_metrics,
    evaluate_case,
    quality_floor_failures,
)
from local_ai_hub.performance_probe import (
    format_probe_summary,
    is_valid_stage,
    percentile,
    validate_stage,
)


def test_model_quality_nan_inf_bool_and_registry_helpers() -> None:
    # NaN grounded rate must fail quality floor, not pass
    failures_nan = quality_floor_failures({"grounded_rate": float("nan")})
    assert "grounded_rate" in failures_nan

    failures_bool = quality_floor_failures({"grounded_rate": True})
    assert "grounded_rate" in failures_bool

    # aggregate_metrics with None or invalid entries
    metrics_empty = aggregate_metrics(None)  # type: ignore[arg-type]
    assert metrics_empty["case_count"] == 0

    metrics_nan = aggregate_metrics([
        {"grounded": True, "latency_ms": float("nan"), "input_tokens": float("inf")},
        {"grounded": False, "latency_ms": 10.0, "input_tokens": 50},
    ])
    assert metrics_nan["case_count"] == 2
    assert metrics_nan["grounded_rate"] == 0.5
    assert metrics_nan["p50_latency_ms"] == 10.0
    assert metrics_nan["input_tokens"] == 50.0

    # evaluate_case with null bytes and whitespace in evidence paths
    case_res = evaluate_case(
        "task-1",
        ["  src/mod.py\x00 "],
        {"path": "src/mod.py"},
        {"path": "src/mod.py"},
    )
    assert case_res["grounded"] is True
    assert case_res["hallucinated_paths"] == []

    registry = CandidateRegistry()
    assert registry.count() == 0
    assert registry.list_candidates() == []

    cand = registry.register_candidate("  cand\x00-1  ", {"grounded_rate": 0.95})
    assert cand["candidate_id"] == "cand-1"
    assert registry.count() == 1
    assert registry.get("cand\x00-1") is not None
    assert len(registry.list_candidates()) == 1

    registry.clear()
    assert registry.count() == 0
    assert registry.get("cand-1") is None


def test_performance_probe_stage_validation_percentile_and_helpers() -> None:
    assert is_valid_stage("http") is True
    assert is_valid_stage("  HTTP\x00 ") is True
    assert is_valid_stage("invalid") is False
    assert is_valid_stage(True) is False
    assert is_valid_stage(None) is False

    assert validate_stage("  http\x00 ") == "http"
    with pytest.raises(ValueError, match="unknown performance stage"):
        validate_stage(True)  # type: ignore[arg-type]

    # Percentile with invalid percentage types
    with pytest.raises(ValueError, match="percentage"):
        percentile([1.0, 2.0], float("nan"))
    with pytest.raises(ValueError, match="percentage"):
        percentile([1.0, 2.0], True)  # type: ignore[arg-type]

    # Samples with NaN/Inf filtered safely
    p50 = percentile([10.0, float("nan"), float("inf"), 20.0, True], 50)  # type: ignore[list-item]
    assert p50 == 15.0

    report = {
        "success": True,
        "stage": "http",
        "iterations": 5,
        "wall_ms": {"p95": 12.34},
    }
    summary = format_probe_summary(report)
    assert "stage=http" in summary
    assert "p95=12.34ms" in summary
    assert format_probe_summary("not-a-dict") == ""
