from __future__ import annotations

import subprocess
import sys

import pytest

from local_ai_hub.async_jobs import AsyncJobManager
from local_ai_hub.scheduler import AffinityScheduler, QueueFullError


class _Runtime:
    def __init__(self, resource: dict[str, object] | None = None, cache_stats: dict[str, int] | None = None) -> None:
        self.resource = resource or {}
        self.cache = cache_stats or {}

    def resource_status(self) -> dict[str, object]:
        return dict(self.resource)

    def cache_stats(self) -> dict[str, int]:
        return dict(self.cache)

    def loaded_model_details(self) -> list[dict[str, object]]:
        return []

    def loaded_models(self) -> list[str]:
        return []

    def unload_model(self, _model: str) -> bool:
        return True

    def prepare_model(self, _model: str) -> list[str]:
        return []


def _scheduler(tmp_path, resource: dict[str, object] | None = None, **scheduler_cfg) -> AffinityScheduler:
    config = {
        "models": {"fast_code": "fast"},
        "scheduler": {"max_parallel": 1, "max_queue": 8, "max_queued_per_tenant": 8, **scheduler_cfg},
    }
    return AffinityScheduler(_Runtime(resource), config)


def test_foreground_admission_is_degraded_under_resource_pressure(tmp_path) -> None:
    scheduler = _scheduler(
        tmp_path,
        {"pressure_level": "high", "context_budget_factor": 0.5, "throttle_background": True},
    )
    try:
        result = scheduler.submit("fast", "tenant-a", "test", lambda: {"success": True})
        assert result["admission"]["state"] == "degraded"
        assert result["admission"]["reason"] == "resource_pressure"
        assert result["admission"]["context_budget_factor"] == 0.5
        assert result["admission"]["queue_age_ms"] >= 0
        assert result["admission"]["retryable"] is False
    finally:
        scheduler.close()


def test_background_admission_rejects_critical_pressure() -> None:
    scheduler = _scheduler(
        None,
        {"pressure_level": "critical", "context_budget_factor": 0.25, "throttle_background": True},
    )
    try:
        with pytest.raises(QueueFullError) as exc_info:
            scheduler.enqueue("fast", "tenant-a", "background", lambda: {"success": True})
        error = exc_info.value
        assert error.admission["state"] == "rejected"
        assert error.admission["reason"] == "resource_pressure"
        assert error.admission["retryable"] is True
    finally:
        scheduler.close()


def test_scheduler_status_marks_bounded_pending_and_cache_stats() -> None:
    cache = {f"entry-{index}": index for index in range(8)}
    runtime = _Runtime(cache_stats=cache)
    scheduler = AffinityScheduler(
        runtime,
        {
            "models": {"fast_code": "fast"},
            "scheduler": {
                "max_parallel": 1,
                "max_queue": 8,
                "max_queued_per_tenant": 8,
                "status_max_items": 2,
                "cache_stats_max_items": 3,
            },
        },
    )
    try:
        jobs = [scheduler.enqueue("fast", "tenant-a", f"queued-{i}", lambda: {"success": True}) for i in range(3)]
        status = scheduler.status()
        assert len(status["pending_jobs"]) == 2
        assert status["pending_jobs_total"] == 3
        assert status["pending_jobs_truncated"] is True
        assert status["cache_stats"]["truncated"] is True
        assert len(status["cache_stats"]["items"]) == 3
        assert all(not job.done.is_set() for job in jobs)
    finally:
        scheduler.close()


def test_async_admission_states_and_queued_result_are_explicit(tmp_path) -> None:
    manager = AsyncJobManager(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "async_jobs": {"max_pending": 1},
        },
        scheduler=None,
        artifacts=None,
        executor=lambda _action, _payload, _tenant: {"success": True},
    )
    try:
        first = manager.submit("tenant-a", "reason", {"task": "first"}, dispatch_delay_seconds=30)
        assert first["admission"]["state"] == "accepted"
        assert first["state"] == "queued"
        assert manager.result("tenant-a", first["job_id"])["success"] is False

        second = manager.submit("tenant-a", "reason", {"task": "second"})
        assert second["admission"]["state"] == "rejected"
        assert second["state"] == "rejected"
        assert second["retryable"] is True
        assert second["terminal"] is False
    finally:
        manager.cancel("tenant-a", first["job_id"])
        manager.close()


def test_async_admission_degrades_with_context_pressure(tmp_path) -> None:
    class _PressureScheduler:
        def _resource_status(self) -> dict[str, object]:
            return {"pressure_level": "high", "context_budget_factor": 0.5, "throttle_background": False}

    manager = AsyncJobManager(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "async_jobs": {"max_pending": 1},
        },
        scheduler=_PressureScheduler(),
        artifacts=None,
        executor=lambda _action, _payload, _tenant: {"success": True},
    )
    try:
        submitted = manager.submit("tenant-a", "reason", {"task": "pressure"}, dispatch_delay_seconds=30)
        assert submitted["admission"]["state"] == "degraded"
        assert submitted["admission"]["context_budget_factor"] == 0.5
    finally:
        manager.cancel("tenant-a", submitted["job_id"])
        manager.close()


def test_async_cancel_terminates_registered_process(tmp_path) -> None:
    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}},
        scheduler=None,
        artifacts=None,
        executor=lambda _action, _payload, _tenant: {"success": True},
    )
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        submitted = manager.submit("tenant-a", "reason", {"task": "process"}, dispatch_delay_seconds=30)
        manager.register_process(submitted["job_id"], process)
        cancelled = manager.cancel("tenant-a", submitted["job_id"])
        process.wait(timeout=3)
        assert cancelled["admission"]["state"] == "accepted"
        assert process.poll() is not None
        assert manager.status("tenant-a", submitted["job_id"])["state"] == "cancelled"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        manager.close()
