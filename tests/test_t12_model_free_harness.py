from __future__ import annotations

from tools.t12_model_free_harness import run_model_free_acceptance


def test_model_free_harness_measures_profile_routing_admission_and_scheduler_stages() -> None:
    report = run_model_free_acceptance()

    assert report["measurement_mode"] == "synthetic_model_free"
    assert report["live_inference"] is False
    assert report["vram_bytes"] is None
    assert report["quality"] == "not_measured"
    assert set(report["profiles"]) == {"integrated", "balanced", "high", "max"}
    assert report["cross_tenant_fairness_wait_ms"] == {"tenant_a": 1000.0, "tenant_b": 2000.0}

    for profile_name, result in report["profiles"].items():
        assert result["route_models"]["fast_code"]
        assert result["route_models"]["heavy_code"]
        assert result["admission_states"] == ["accepted"] * 3
        assert result["queue_rejection"] == {
            "state": "rejected",
            "reason": "queue_limit",
            "executor_invoked": False,
        }
        assert result["load_count_by_model"] == {
            result["route_models"]["fast_code"]: 1,
            result["route_models"]["heavy_code"]: 1,
        }
        assert result["model_switch_count"] == 2
        assert result["queue_wait_ms"][1] >= 10
        assert len(result["inference_service_ms"]) == 3
        assert all(value >= 0 for value in result["inference_service_ms"])
        assert all(value >= 0 for value in result["model_prepare_ms"])
        assert len(result["fairness_wait_ms"]) == 3
        assert all(value >= 0 for value in result["fairness_wait_ms"])
        assert len(result["synthetic_inference_ms"]) == 3
        assert all(value >= 0 for value in result["synthetic_inference_ms"])
        assert profile_name in report["profiles"]
