from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from local_ai_hub.scheduler import AffinityScheduler


SCENARIOS = ("scheduler", "batch", "deadline", "overload", "cancel", "fallback")


def _scheduler(runtime: Any) -> AffinityScheduler:
    scheduler = object.__new__(AffinityScheduler)
    scheduler.runtime = runtime
    return scheduler


def test_t12_cross_model_admission_defers_to_post_unload_check() -> None:
    class Runtime:
        def supports_post_unload_admission(self, model: str) -> bool:
            return model == "target-model"

        def resource_status(self) -> dict[str, Any]:
            return {
                "pressure_level": "nominal",
                "vram_total_mb": 8192.0,
                "vram_available_mb": 1024.0,
            }

    scheduler = _scheduler(Runtime())
    scheduler.config = {
        "scheduler": {"model_vram_estimates_bytes": {"target-model": 7 * 1024**3}},
    }
    scheduler._model_vram_bytes = {"resident-model": 5 * 1024**3}
    scheduler._active_model = "resident-model"
    scheduler.unload_others = True

    admission = scheduler._admission(background=False, model="target-model")

    assert admission["state"] == "degraded"
    assert admission["reason"] == "vram_admission_deferred_until_unload"
    assert admission["vram_admission"] == "deferred"
    assert admission["vram_incremental_required_bytes"] == 7 * 1024**3


def test_t12_model_switch_uses_fresh_post_unload_vram_and_records_admission() -> None:
    import threading
    from collections import Counter
    from types import SimpleNamespace

    class Runtime:
        available_mb = 1024.0

        def supports_post_unload_admission(self, model: str) -> bool:
            return model == "target-model"

        def resource_status(self) -> dict[str, Any]:
            return {
                "pressure_level": "nominal",
                "vram_total_mb": 8192.0,
                "vram_available_mb": self.available_mb,
            }

        def loaded_model_details(self) -> list[dict[str, Any]]:
            return []

        def prepare_model(self, model: str, *, post_unload_admission: Any, **_kwargs: Any) -> list[str]:
            del model
            events.append("unload")
            self.available_mb = 7168.0
            observed = post_unload_admission()
            events.append(f"admitted:{observed['vram_available_bytes']}")
            return ["resident-model"]

    events: list[str] = []
    runtime = Runtime()
    scheduler = _scheduler(runtime)
    scheduler._cond = threading.Condition()
    scheduler._pending = [SimpleNamespace(
        model="target-model", done=threading.Event(), cancel_event=None, deadline=None,
        model_switch_receipt=None, admission={}, error=None,
    )]
    scheduler._model_vram_bytes = {"resident-model": 5 * 1024**3, "target-model": 7 * 1024**3}
    scheduler._active_model = "resident-model"
    scheduler._active_since = 1.0
    scheduler._active_dispatched = 0
    scheduler._last_switch = 0.0
    scheduler._switch_sequence = 0
    scheduler._stats = Counter()
    scheduler._model_blocked_until = {}
    scheduler._model_last_error = {}
    scheduler.switch_failure_cooldown = 1.0
    scheduler.unload_others = True
    scheduler.config = {}

    assert scheduler._perform_switch("target-model") is True

    assert events == ["unload", f"admitted:{7168 * 1024**2}"]
    receipt = scheduler._pending[0].model_switch_receipt
    assert receipt["post_unload_admission"]["state"] == "admitted"
    assert receipt["post_unload_admission"]["vram_incremental_required_bytes"] == 7 * 1024**3


def test_t12_post_unload_rejection_is_reported_without_model_cooldown() -> None:
    import threading
    from collections import Counter
    from types import SimpleNamespace

    class Runtime:
        available_mb = 1024.0

        def supports_post_unload_admission(self, model: str) -> bool:
            return model == "target-model"

        def resource_status(self) -> dict[str, Any]:
            return {
                "pressure_level": "nominal",
                "vram_total_mb": 8192.0,
                "vram_available_mb": self.available_mb,
            }

        def loaded_model_details(self) -> list[dict[str, Any]]:
            return []

        def prepare_model(self, model: str, *, post_unload_admission: Any, **_kwargs: Any) -> list[str]:
            del model
            admission = post_unload_admission()
            error = RuntimeError("post-unload admission rejected")
            error.admission = admission
            error.evicted_models = ["resident-model"]
            raise error

    runtime = Runtime()
    scheduler = _scheduler(runtime)
    scheduler._cond = threading.Condition()
    pending = SimpleNamespace(
        model="target-model", done=threading.Event(), cancel_event=None, deadline=None,
        model_switch_receipt=None, admission={"state": "degraded"}, error=None,
    )
    scheduler._pending = [pending]
    scheduler._model_vram_bytes = {"resident-model": 5 * 1024**3, "target-model": 7 * 1024**3}
    scheduler._active_model = "resident-model"
    scheduler._active_since = 1.0
    scheduler._active_dispatched = 0
    scheduler._last_switch = 0.0
    scheduler._switch_sequence = 0
    scheduler._stats = Counter()
    scheduler._model_blocked_until = {}
    scheduler._model_last_error = {}
    scheduler.switch_failure_cooldown = 30.0
    scheduler.unload_others = True
    scheduler.config = {"scheduler": {"model_vram_estimates_bytes": {"target-model": 7 * 1024**3}}}
    runtime.available_mb = 6 * 1024.0

    assert scheduler._perform_switch("target-model") is False

    assert pending.done.is_set()
    assert pending.admission["state"] == "rejected"
    assert pending.admission["reason"] == "vram_budget_after_unload"
    assert pending.model_switch_receipt["admission_rejected"] is True
    assert "failure" not in pending.model_switch_receipt
    assert scheduler._model_blocked_until == {}
    assert scheduler._active_model is None


def test_app_connects_vram_balancer_to_scheduler(tmp_path: Path, monkeypatch: Any) -> None:
    from local_ai_hub import app as app_module

    expected = {
        "available": True,
        "pressure_level": "nominal",
        "context_budget_factor": 1.0,
        "throttle_background": False,
        "vram_total_mb": 8192.0,
        "vram_available_mb": 6144.0,
    }

    class StubVRAMBalancer:
        def __init__(self, config: dict[str, Any]):
            del config

        def status(self) -> dict[str, Any]:
            return dict(expected)

    monkeypatch.setattr(app_module, "VRAMBalancer", StubVRAMBalancer)
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[server]\n"
        'bind = "127.0.0.1"\n'
        "port = 11497\n"
        f"state_dir = {json.dumps(str(tmp_path / 'state'))}\n\n"
        "[prewarm]\n"
        "enabled = false\n\n"
        "[observability]\n"
        "enabled = false\n\n"
        "[resilience]\n"
        "watchdog_enabled = false\n",
        encoding="utf-8",
    )

    app = app_module.LocalAIApp(str(config_path))
    try:
        assert app.scheduler._resource_status() == expected
    finally:
        app.close()


def test_t12_scheduler_seeds_startup_vram_for_loaded_models() -> None:
    class Runtime:
        def loaded_model_details(self) -> list[dict[str, Any]]:
            return [
                {"name": "resident-model", "context_length": 8192, "vram_bytes": 1_234_567},
                {"name": "second-resident", "context_length": 8192, "vram_bytes": 2_345_678},
            ]

        def loaded_models(self) -> list[str]:
            return ["resident-model", "second-resident"]

    scheduler = AffinityScheduler(Runtime(), {"scheduler": {"max_loaded_models": 2}, "models": {}})
    try:
        assert scheduler._model_vram_bytes == {
            "resident-model": 1_234_567,
            "second-resident": 2_345_678,
        }
    finally:
        scheduler.close()


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


def test_t12_model_switch_admission_does_not_overstate_measured_reclaimable_vram() -> None:
    class Runtime:
        def resource_status(self) -> dict[str, Any]:
            return {
                "pressure_level": "critical",
                "context_budget_factor": 0.25,
                "throttle_background": False,
                "vram_total_mb": 8188.0,
                "vram_available_mb": 1020.0,
            }

    scheduler = _scheduler(Runtime())
    scheduler.config = {
        "scheduler": {
            "model_vram_estimates_bytes": {
                "qwen3.5:9b": 6_096_900_060,
                "qwen2.5-coder:7b": 6_853_448_695,
            },
        },
    }
    scheduler._active_model = "qwen3.5:9b"
    scheduler._model_vram_bytes = {"qwen3.5:9b": 5_542_636_418}
    scheduler.unload_others = True

    admission = scheduler._admission(background=False, model="qwen2.5-coder:7b")

    assert admission["state"] in {"rejected", "degraded"}
    assert admission["vram_admission"] == "rejected"
    assert admission["vram_admission_budget_bytes"] == 1020 * 1024 * 1024 + 5_542_636_418
    assert admission["vram_admission_budget_bytes"] < admission["vram_incremental_required_bytes"]


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


def test_t12_scheduler_does_not_count_unobserved_configured_resident_vram_as_reclaimable() -> None:
    class Runtime:
        def resource_status(self) -> dict[str, Any]:
            return {
                "pressure_level": "nominal",
                "context_budget_factor": 1.0,
                "throttle_background": False,
                "vram_total_mb": 8192.0,
                "vram_available_mb": 1024.0,
            }

    resident_estimate = 4 * 1024 * 1024 * 1024
    target_estimate = 5 * 1024 * 1024 * 1024
    scheduler = _scheduler(Runtime())
    scheduler.config = {
        "scheduler": {
            "model_vram_estimates_bytes": {
                "resident-model": resident_estimate,
                "target-model": target_estimate,
            },
        },
    }
    scheduler._model_vram_bytes = {}
    scheduler._active_model = "resident-model"
    scheduler.unload_others = True

    admission = scheduler._admission(background=False, model="target-model")

    assert admission["vram_admission_budget_bytes"] == 1024 * 1024 * 1024
    assert admission["vram_incremental_required_bytes"] == target_estimate
    assert admission["vram_admission"] == "rejected"
    assert admission["vram_estimate_source"] == "configured"


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


def test_t12_scheduler_observes_vram_from_facade_without_optional_keywords() -> None:
    class Runtime:
        def loaded_model_details(self) -> list[dict[str, Any]]:
            return [{"name": "target-model", "vram_bytes": 2048}]

    scheduler = _scheduler(Runtime())

    measured = scheduler._observe_model_vram_bytes("target-model", should_stop=None, deadline=None)

    assert measured == 2048


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


def test_t12_scheduler_close_signals_running_job_cancellation() -> None:
    import threading
    from local_ai_hub.scheduler import SchedulerCancelledError

    class Runtime:
        def resource_status(self) -> dict[str, Any]:
            return {"pressure_level": "nominal", "context_budget_factor": 1.0}

        def loaded_model_details(self) -> list[dict[str, Any]]:
            return [{"name": "fast", "context_length": 131072}]

        def loaded_models(self) -> list[str]:
            return ["fast"]

        def cache_stats(self) -> dict[str, int]:
            return {}

    started = threading.Event()
    cancel_event = threading.Event()
    worker_cancelled = threading.Event()
    release_worker = threading.Event()
    scheduler = AffinityScheduler(
        Runtime(),
        {
            "models": {"fast_code": "fast"},
            "scheduler": {"max_parallel": 1},
            "resilience": {"scheduler_wait_timeout_seconds": 5},
        },
    )
    outcome: list[dict[str, Any]] = []

    def execute() -> dict[str, Any]:
        started.set()
        if cancel_event.wait(2):
            worker_cancelled.set()
        release_worker.wait(2)
        return {"success": False}

    def submit() -> None:
        try:
            outcome.append(scheduler.submit(
                "fast", "tenant", "test", execute, cancel_event=cancel_event
            ))
        except SchedulerCancelledError as exc:
            outcome.append({"cancelled": True, "state": exc.state})

    caller = threading.Thread(target=submit)
    closed = False
    try:
        caller.start()
        assert started.wait(1)
        scheduler.close()
        closed = True
        assert cancel_event.is_set()
        assert worker_cancelled.wait(1)
        caller.join(1)
        assert not caller.is_alive()
        assert outcome == [{"cancelled": True, "state": "running"}]
    finally:
        cancel_event.set()
        release_worker.set()
        if not closed:
            scheduler.close()
        caller.join(1)


def test_t12_cancelled_dispatched_job_does_not_start_execute() -> None:
    import threading
    from local_ai_hub.scheduler import Job

    started: list[bool] = []
    cancel = threading.Event()
    cancel.set()
    job = Job(
        id=1,
        model="fixture-model",
        tenant="tenant-a",
        source="test",
        priority=5,
        execute=lambda: (started.append(True) or {"success": True}),
        cancel_event=cancel,
    )
    scheduler = AffinityScheduler.__new__(AffinityScheduler)
    scheduler._cond = threading.Condition()
    scheduler._stats = {"completed": 0, "failed": 0, "background_completed": 0, "background_failed": 0}
    scheduler._inflight = 1
    scheduler._inflight_jobs = {job.id: job}
    scheduler._inflight_background = 0
    scheduler._inflight_by_tenant = {job.tenant: 1}
    scheduler._last_foreground_activity = 0.0

    scheduler._run_job(job)

    assert started == []
    assert job.done.is_set()
