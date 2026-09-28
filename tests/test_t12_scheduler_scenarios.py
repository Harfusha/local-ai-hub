from __future__ import annotations

from typing import Any

from local_ai_hub.scheduler import AffinityScheduler


SCENARIOS = ("scheduler", "batch", "deadline", "overload", "cancel", "fallback")


def _scheduler(runtime: Any) -> AffinityScheduler:
    scheduler = object.__new__(AffinityScheduler)
    scheduler.runtime = runtime
    return scheduler


def test_t12_scheduler_adapter_preserves_safe_missing_measurement_names() -> None:
    class Runtime:
        def run_benchmark_scenario(self, **kwargs: Any) -> dict[str, Any]:
            del kwargs
            return {
                "success": False,
                "scenario": "scheduler",
                "status": "unmeasured",
                "metrics": {},
                "missing_fields": ["vram_admission", "batch_bucket"],
            }

    scheduler = _scheduler(Runtime())
    result = scheduler.run_benchmark_scenario(
        name="scheduler",
        contract={"scenario": "scheduler", "required_fields": ["vram_admission"]},
    )

    assert result["success"] is False
    assert result["error_type"] == "scenario_measurement_missing"
    assert result["missing_fields"] == ["batch_bucket", "vram_admission"]


def test_t12_scheduler_admission_reports_observed_vram_budget() -> None:
    class Runtime:
        def __init__(self, *, pressure: str, available_mb: float, throttle: bool) -> None:
            self.pressure = pressure
            self.available_mb = available_mb
            self.throttle = throttle

        def resource_status(self) -> dict[str, Any]:
            return {
                "pressure_level": self.pressure,
                "context_budget_factor": 1.0,
                "throttle_background": self.throttle,
                "vram_total_mb": 8192.0,
                "vram_available_mb": self.available_mb,
            }

    accepted_scheduler = _scheduler(Runtime(pressure="nominal", available_mb=4096.0, throttle=False))
    accepted_scheduler.config = {"scheduler": {}}
    accepted_scheduler._model_vram_bytes = {"target-model": 3 * 1024 * 1024 * 1024}
    accepted_scheduler._active_model = None
    accepted_scheduler.unload_others = False
    accepted = accepted_scheduler._admission(background=False, model="target-model")

    assert accepted["vram_admission"] == "admitted"
    assert accepted["vram_budget_bytes"] == 8192 * 1024 * 1024
    assert accepted["vram_available_bytes"] == 4096 * 1024 * 1024
    assert accepted["vram_admission_budget_bytes"] == 4096 * 1024 * 1024
    assert accepted["vram_incremental_required_bytes"] == 3 * 1024 * 1024 * 1024
    assert accepted["vram_estimate_source"] == "measured"

    rejected_scheduler = _scheduler(Runtime(pressure="nominal", available_mb=512.0, throttle=False))
    rejected_scheduler.config = {"scheduler": {}}
    rejected_scheduler._model_vram_bytes = {"target-model": 3 * 1024 * 1024 * 1024}
    rejected_scheduler._active_model = None
    rejected_scheduler.unload_others = False
    rejected = rejected_scheduler._admission(background=False, model="target-model")

    assert rejected["state"] == "rejected"
    assert rejected["reason"] == "vram_budget"
    assert rejected["vram_admission"] == "rejected"


def test_t12_scheduler_uses_explicit_cold_model_vram_estimate() -> None:
    class Runtime:
        def __init__(self, available_mb: float) -> None:
            self.available_mb = available_mb

        def resource_status(self) -> dict[str, Any]:
            return {
                "pressure_level": "nominal",
                "context_budget_factor": 1.0,
                "throttle_background": False,
                "vram_total_mb": 8192.0,
                "vram_available_mb": self.available_mb,
            }

    estimate = 3 * 1024 * 1024 * 1024
    accepted_scheduler = _scheduler(Runtime(available_mb=4096.0))
    accepted_scheduler.config = {
        "scheduler": {"model_vram_estimates_bytes": {"Target-Model": estimate}},
    }
    accepted_scheduler._model_vram_bytes = {}
    accepted_scheduler._active_model = None
    accepted_scheduler.unload_others = False
    accepted = accepted_scheduler._admission(background=False, model="target-model")

    assert accepted["vram_admission"] == "admitted"
    assert accepted["vram_estimate_source"] == "configured"
    assert accepted["vram_incremental_required_bytes"] == estimate

    rejected_scheduler = _scheduler(Runtime(available_mb=2048.0))
    rejected_scheduler.config = accepted_scheduler.config
    rejected_scheduler._model_vram_bytes = {}
    rejected_scheduler._active_model = None
    rejected_scheduler.unload_others = False
    rejected = rejected_scheduler._admission(background=False, model="target-model")

    assert rejected["state"] == "rejected"
    assert rejected["reason"] == "vram_budget"
    assert rejected["vram_estimate_source"] == "configured"


def test_t12_scheduler_labels_unestimated_cold_model_without_fabricated_size() -> None:
    class Runtime:
        def resource_status(self) -> dict[str, Any]:
            return {
                "pressure_level": "nominal",
                "context_budget_factor": 1.0,
                "throttle_background": False,
                "vram_total_mb": 8192.0,
                "vram_available_mb": 4096.0,
            }

    scheduler = _scheduler(Runtime())
    scheduler.config = {"scheduler": {}}
    scheduler._model_vram_bytes = {}
    scheduler._active_model = None
    scheduler.unload_others = False

    admission = scheduler._admission(background=False, model="unknown-model")

    assert admission["vram_admission"] == "unknown"
    assert admission["vram_estimate_source"] == "unknown"
    assert admission["vram_admission_budget_bytes"] == 4096 * 1024 * 1024
    assert "vram_incremental_required_bytes" not in admission


def test_t12_scheduler_observes_loaded_model_vram_bytes() -> None:
    class Runtime:
        def loaded_model_details(self, *, should_stop=None, deadline=None) -> list[dict[str, Any]]:
            return [
                {"name": "other-model", "vram_bytes": 512},
                {"name": "target-model", "vram_bytes": 1024},
                {"name": "TARGET-MODEL", "vram_bytes": 2048},
            ]

    scheduler = _scheduler(Runtime())

    measured = scheduler._observe_model_vram_bytes("target-model", should_stop=None, deadline=None)

    assert measured == 3072


def test_t12_scheduler_treats_zero_vram_report_as_unmeasured() -> None:
    class Runtime:
        def loaded_model_details(self, *, should_stop=None, deadline=None) -> list[dict[str, Any]]:
            return [{"name": "target-model", "vram_bytes": 0}]

    scheduler = _scheduler(Runtime())

    measured = scheduler._observe_model_vram_bytes("target-model", should_stop=None, deadline=None)

    assert measured is None


def test_t12_scheduler_scenario_hook_forwards_measured_metrics_for_all_cases() -> None:
    class Runtime:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any], Any]] = []

        def run_benchmark_scenario(self, *, name: str, contract: dict[str, Any], scheduler: Any) -> dict[str, Any]:
            self.calls.append((name, contract, scheduler))
            return {
                "scenario": name,
                "status": "measured",
                "metrics": {
                    "observed_value": {"scenario": name, "count": 2},
                    "unrequested_payload": "must not escape",
                },
                "receipt_id": f"fixture-receipt-{name}",
            }

    runtime = Runtime()
    scheduler = _scheduler(runtime)

    for name in SCENARIOS:
        contract = {
            "scenario": name,
            "required_fields": ["observed_value"],
            "concurrency_limit": 2,
            "quality_floor_pct": 80.0,
        }
        result = scheduler.run_benchmark_scenario(name=name, contract=contract)

        assert result == {
            "success": True,
            "observed_value": {"scenario": name, "count": 2},
            "receipt_id": f"fixture-receipt-{name}",
        }

    assert [name for name, _, _ in runtime.calls] == list(SCENARIOS)
    assert all(owner is scheduler for _, _, owner in runtime.calls)


def test_t12_scheduler_scenario_hook_fails_closed_without_runtime_executor() -> None:
    scheduler = _scheduler(object())

    result = scheduler.run_benchmark_scenario(
        name="scheduler",
        contract={"scenario": "scheduler", "required_fields": ["queue_age_ms"]},
    )

    assert result.get("success") is False
    assert "queue_age_ms" not in result
    assert "receipt_id" not in result


def test_t12_scheduler_scenario_hook_rejects_unmeasured_or_incomplete_receipts() -> None:
    invalid_results = (
        {
            "scenario": "scheduler",
            "status": "planned",
            "metrics": {"queue_age_ms": 12.0},
            "receipt_id": "fixture-not-measured",
        },
        {
            "scenario": "scheduler",
            "status": "measured",
            "metrics": {"other": 12.0},
            "receipt_id": "fixture-missing-metric",
        },
        {
            "scenario": "scheduler",
            "status": "measured",
            "metrics": {"queue_age_ms": 12.0},
            "receipt_id": "  ",
        },
    )

    class Runtime:
        def __init__(self) -> None:
            self.result: dict[str, Any] = {}

        def run_benchmark_scenario(self, *, name: str, contract: dict[str, Any], scheduler: Any) -> dict[str, Any]:
            return self.result

    runtime = Runtime()
    scheduler = _scheduler(runtime)
    contract = {"scenario": "scheduler", "required_fields": ["queue_age_ms"]}

    for runtime.result in invalid_results:
        result = scheduler.run_benchmark_scenario(name="scheduler", contract=contract)
        assert result.get("success") is False
        assert "queue_age_ms" not in result
        assert "receipt_id" not in result


def test_t12_scheduler_scenario_hook_rejects_unknown_scenario_before_runtime_call() -> None:
    class Runtime:
        called = False

        def run_benchmark_scenario(self, *, name: str, contract: dict[str, Any], scheduler: Any) -> dict[str, Any]:
            self.called = True
            return {}

    runtime = Runtime()
    result = _scheduler(runtime).run_benchmark_scenario(
        name="not-a-t12-scenario",
        contract={"scenario": "not-a-t12-scenario", "required_fields": ["value"]},
    )

    assert result.get("success") is False
    assert runtime.called is False


def test_t12_scheduler_scenario_hook_keeps_requested_fields_when_runtime_mutates_contract() -> None:
    class Runtime:
        def run_benchmark_scenario(self, *, name: str, contract: dict[str, Any], scheduler: Any) -> dict[str, Any]:
            contract["required_fields"][:] = ["unrequested_payload"]
            return {
                "scenario": name,
                "status": "measured",
                "metrics": {
                    "queue_age_ms": 12.0,
                    "unrequested_payload": "must not escape",
                },
                "receipt_id": "fixture-mutation-receipt",
            }

    result = _scheduler(Runtime()).run_benchmark_scenario(
        name="scheduler",
        contract={"scenario": "scheduler", "required_fields": ["queue_age_ms"]},
    )

    assert result == {
        "success": True,
        "queue_age_ms": 12.0,
        "receipt_id": "fixture-mutation-receipt",
    }
