"""Reproducible T12 routing/scheduler measurement without a model backend.

This exercises the real router and affinity scheduler. A local fake runtime records
model preparation, and synthetic executor callbacks provide service timings. It does
not call Ollama/llama.cpp, measure VRAM, or score model output quality.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import threading
import time
from typing import Any, Callable

from local_ai_hub.hardware import PROFILE_OVERRIDES
from local_ai_hub.router import ModelRouter
from local_ai_hub.scheduler import AffinityScheduler, Job, QueueFullError


_PROFILES = ("integrated", "balanced", "high", "max")


def _measure_cross_tenant_fairness() -> dict[str, float]:
    """Run deterministic virtual-time picks through the production fairness policy."""
    scheduler = object.__new__(AffinityScheduler)
    scheduler._active_model = "synthetic-model"
    scheduler._inflight_by_tenant = {}
    scheduler.max_inflight_per_tenant = 2
    scheduler._tenant_vruntime = {"tenant-a": 0, "tenant-b": 0}

    def job(job_id: int, tenant: str, created_at: float) -> Job:
        return Job(job_id, "synthetic-model", tenant, "model-free", 1, lambda: {"success": True}, created_at=created_at)

    first_a = job(1, "tenant-a", 1.0)
    waiting_a = job(2, "tenant-a", 3.0)
    first_b = job(3, "tenant-b", 2.0)
    waiting_b = job(4, "tenant-b", 4.0)
    selected = scheduler._choose_job_for_active_model(10.0, [first_a, waiting_a, first_b, waiting_b])
    if selected is not first_a:
        raise RuntimeError("synthetic fairness fixture selected unexpected first tenant")
    scheduler._tenant_vruntime["tenant-a"] += 1
    selected = scheduler._choose_job_for_active_model(11.0, [waiting_a, first_b, waiting_b])
    if selected is not first_b:
        raise RuntimeError("synthetic fairness fixture did not rotate tenants")
    scheduler._tenant_vruntime["tenant-b"] += 1
    scheduler._choose_job_for_active_model(13.0, [waiting_a, waiting_b])
    return {
        "tenant_a": round(waiting_a.fairness_wait_ms, 3),
        "tenant_b": round(waiting_b.fairness_wait_ms, 3),
    }


class _SyntheticRuntime:
    def __init__(self) -> None:
        self.loaded: list[str] = []
        self.prepared: list[str] = []

    def resource_status(self) -> dict[str, Any]:
        # No VRAM values: model-free admission must not imply device capacity.
        return {"pressure_level": "nominal", "context_budget_factor": 1.0}

    def loaded_model_details(self, *, force_refresh: bool = False) -> list[dict[str, str]]:
        del force_refresh
        return [{"name": model} for model in self.loaded]

    def loaded_models(self) -> list[str]:
        return list(self.loaded)

    def cache_stats(self) -> dict[str, int]:
        return {}

    def prepare_model(self, model: str, **_kwargs: Any) -> list[str]:
        evicted = [loaded for loaded in self.loaded if loaded != model]
        self.loaded[:] = [model]
        self.prepared.append(model)
        time.sleep(0.001)
        return evicted


def _measure_profile(profile_name: str) -> dict[str, Any]:
    profile = PROFILE_OVERRIDES[profile_name]
    models = dict(profile["models"])
    router = ModelRouter({"models": models})
    fast_route = router.classify("write one function", task_type="code", complexity="fast")
    heavy_route = router.classify("refactor several modules", task_type="code", complexity="heavy")
    fast_model = str(fast_route["model"])
    heavy_model = str(heavy_route["model"])

    runtime = _SyntheticRuntime()
    scheduler = AffinityScheduler(
        runtime,
        {
            "models": models,
            "model_execution": {},
            "scheduler": {
                "max_parallel": 1,
                "max_inflight_per_tenant": 1,
                "max_queue": 1,
                "max_queued_per_tenant": 1,
                "max_loaded_models": 1,
                "affinity_batch_jobs": 1,
                "affinity_batch_seconds": 0,
            },
            "server": {"request_timeout_seconds": 3},
        },
    )

    first_started = threading.Event()
    release_first = threading.Event()
    queued_started = threading.Event()
    results: dict[str, dict[str, Any]] = {}
    errors: dict[str, BaseException] = {}
    rejected_executor_called = threading.Event()

    def timed_executor(*, started: threading.Event | None = None, gate: threading.Event | None = None) -> dict[str, Any]:
        if started is not None:
            started.set()
        begin = time.perf_counter()
        if gate is not None:
            if not gate.wait(3):
                raise TimeoutError("synthetic inference gate timed out")
        else:
            time.sleep(0.005)
        return {
            "success": True,
            "synthetic_inference_ms": round((time.perf_counter() - begin) * 1000, 3),
        }

    def submit_named(name: str, model: str, execute: Callable[[], dict[str, Any]]) -> None:
        try:
            results[name] = scheduler.submit(
                model, "tenant-a", "t12-model-free", execute, wait_timeout=2,
            )
        except BaseException as exc:  # preserve worker exceptions for the caller
            errors[name] = exc

    first_thread = threading.Thread(
        target=submit_named,
        args=("first", fast_model, lambda: timed_executor(started=first_started, gate=release_first)),
        daemon=True,
    )
    queued_thread = threading.Thread(
        target=submit_named,
        args=("queued", fast_model, lambda: timed_executor(started=queued_started)),
        daemon=True,
    )
    try:
        first_thread.start()
        if not first_started.wait(2):
            raise TimeoutError("first synthetic inference did not start")

        queued_thread.start()
        with scheduler._cond:
            queued = scheduler._cond.wait_for(
                lambda: any(job.model == fast_model for job in scheduler._pending), timeout=2,
            )
        if not queued:
            raise TimeoutError("second synthetic inference did not enter the queue")

        queue_rejection = {"state": "accepted", "reason": "", "executor_invoked": False}
        try:
            scheduler.submit(
                fast_model, "tenant-a", "t12-model-free-overflow",
                lambda: (rejected_executor_called.set() or {"success": True}),
                wait_timeout=1,
            )
        except QueueFullError as exc:
            admission = dict(exc.admission or {})
            queue_rejection = {
                "state": str(admission.get("state", "")),
                "reason": str(admission.get("reason", "")),
                "executor_invoked": rejected_executor_called.is_set(),
            }

        # Hold active callback so queue wait is measurable and reproducible.
        time.sleep(0.025)
        release_first.set()
        first_thread.join(timeout=3)
        queued_thread.join(timeout=3)
        if first_thread.is_alive() or queued_thread.is_alive():
            raise TimeoutError("synthetic queue scenario did not drain")
        if errors:
            raise RuntimeError(f"synthetic scheduler jobs failed: {sorted(errors)}")

        heavy_result = scheduler.submit(
            heavy_model, "tenant-a", "t12-model-free",
            lambda: timed_executor(), wait_timeout=2,
        )
        results["heavy"] = heavy_result

        all_results = [results[name] for name in ("first", "queued", "heavy")]
        switches = [
            result.get("_lah_scheduler_model_switch", {})
            for result in all_results
            if isinstance(result.get("_lah_scheduler_model_switch"), dict)
        ]
        return {
            "route_models": {"fast_code": fast_model, "heavy_code": heavy_model},
            "admission_states": [str(result.get("admission_state", "")) for result in all_results],
            "queue_rejection": queue_rejection,
            "load_count_by_model": dict(Counter(runtime.prepared)),
            "queue_wait_ms": [round(float(result.get("_lah_scheduler_queue_wait_ms", -1)), 3) for result in all_results],
            "fairness_wait_ms": [round(float(result.get("_lah_scheduler_fairness_wait_ms", -1)), 3) for result in all_results],
            "inference_service_ms": [round(float(result.get("_lah_scheduler_service_ms", -1)), 3) for result in all_results],
            "model_prepare_ms": [round(float(event.get("model_prepare_ms", -1)), 3) for event in switches],
            "model_switch_count": len(switches),
            "synthetic_inference_ms": [round(float(result.get("synthetic_inference_ms", -1)), 3) for result in all_results],
        }
    finally:
        release_first.set()
        first_thread.join(timeout=3)
        queued_thread.join(timeout=3)
        scheduler.close()


def run_model_free_acceptance(profiles: tuple[str, ...] = _PROFILES) -> dict[str, Any]:
    """Measure real router/scheduler paths with synthetic, model-free callbacks."""
    unknown = sorted(set(profiles) - set(_PROFILES))
    if unknown:
        raise ValueError(f"unsupported hardware profiles: {', '.join(unknown)}")
    if not profiles:
        raise ValueError("at least one hardware profile is required")
    return {
        "measurement_mode": "synthetic_model_free",
        "live_inference": False,
        "vram_bytes": None,
        "quality": "not_measured",
        "cross_tenant_fairness_wait_ms": _measure_cross_tenant_fairness(),
        "profiles": {name: _measure_profile(name) for name in profiles},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", nargs="+", choices=_PROFILES, default=list(_PROFILES))
    args = parser.parse_args()
    print(json.dumps(run_model_free_acceptance(tuple(args.profiles)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
