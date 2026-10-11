from __future__ import annotations

import subprocess
import sys

import pytest

from local_ai_hub.async_jobs import AsyncJobManager
import local_ai_hub.async_jobs as async_jobs
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

    def prepare_model(self, _model: str, **_kwargs: object) -> list[str]:
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


def test_async_cleanup_uses_managed_process_tree_owner(tmp_path, monkeypatch) -> None:
    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}},
        scheduler=None,
        artifacts=None,
        executor=lambda _action, _payload, _tenant: {"success": True},
    )

    class _ManagedProcess:
        pid = 12345
        _local_ai_process_group = 12345
        _local_ai_process_identity = {"pid": 12345, "creation_identity": 1}

        def __init__(self) -> None:
            self.waited = False

        def poll(self):
            return 0 if self.waited else None

        def wait(self, timeout=None):
            self.waited = True
            return 0

        def terminate(self):
            raise AssertionError("managed process tree must use its ownership handle")

    process = _ManagedProcess()
    calls = []
    monkeypatch.setattr(
        async_jobs,
        "terminate_tree",
        lambda pid, **kwargs: calls.append((pid, kwargs)) or True,
    )
    try:
        manager.register_process("job", process)
        manager._cleanup_processes("job")
        assert calls == [(process.pid, {"grace_seconds": 1.0, "process_handle": process})]
        assert process.waited is True
    finally:
        manager.close()


def test_async_cleanup_does_not_assume_exited_leader_means_tree_stopped(tmp_path, monkeypatch) -> None:
    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}},
        scheduler=None,
        artifacts=None,
        executor=lambda _action, _payload, _tenant: {"success": True},
    )

    class _ExitedManagedProcess:
        pid = 12348
        _local_ai_process_group = 12348
        _local_ai_process_identity = {"pid": 12348, "creation_identity": 4}

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            raise AssertionError("managed process tree must not use leader-only termination")

    process = _ExitedManagedProcess()
    calls = []
    monkeypatch.setattr(
        async_jobs,
        "terminate_tree",
        lambda pid, **kwargs: calls.append((pid, kwargs)) or False,
    )
    try:
        manager.register_process("job", process)
        assert manager._cleanup_processes("job") is False
        assert calls == [(process.pid, {"grace_seconds": 1.0, "process_handle": process})]
        assert manager._processes["job"] == [process]
    finally:
        manager.close()


def test_async_cancel_reports_unknown_when_tree_cleanup_is_unconfirmed(tmp_path, monkeypatch) -> None:
    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}},
        scheduler=None,
        artifacts=None,
        executor=lambda _action, _payload, _tenant: {"success": True},
    )

    class _ManagedProcess:
        pid = 12346
        _local_ai_process_group = 12346
        _local_ai_process_identity = {"pid": 12346, "creation_identity": 2}

        def poll(self):
            return None

        def wait(self, timeout=None):
            raise AssertionError("unconfirmed cleanup must not wait as if the tree stopped")

        def terminate(self):
            raise AssertionError("managed process tree must not fall back to a leader signal")

    monkeypatch.setattr(async_jobs, "terminate_tree", lambda *_args, **_kwargs: False)
    process = _ManagedProcess()
    try:
        submitted = manager.submit("tenant-a", "reason", {"task": "cleanup"}, dispatch_delay_seconds=30)
        manager.register_process(submitted["job_id"], process)
        cancelled = manager.cancel("tenant-a", submitted["job_id"])
        assert cancelled["state"] == "outcome_unknown"
        assert cancelled["outcome_unknown"] is True
        assert cancelled["retryable"] is False
        assert manager.status("tenant-a", submitted["job_id"])["state"] == "outcome_unknown"
        assert manager._processes[submitted["job_id"]] == [process]
    finally:
        manager.close()


def test_async_worker_records_unknown_when_process_tree_cleanup_fails(tmp_path, monkeypatch) -> None:
    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}},
        scheduler=None,
        artifacts=None,
        executor=lambda _action, _payload, _tenant: {"success": True},
    )

    class _ManagedProcess:
        pid = 12347
        _local_ai_process_group = 12347
        _local_ai_process_identity = {"pid": 12347, "creation_identity": 3}

        def poll(self):
            return None

        def wait(self, timeout=None):
            raise AssertionError("unconfirmed cleanup must not report a stopped process")

        def terminate(self):
            raise AssertionError("managed process tree must not fall back to a leader signal")

    monkeypatch.setattr(async_jobs, "terminate_tree", lambda *_args, **_kwargs: False)
    try:
        submitted = manager.submit("tenant-a", "reason", {"task": "cleanup"}, dispatch_delay_seconds=1.0)
        manager.register_process(submitted["job_id"], _ManagedProcess())
        result = manager.wait("tenant-a", submitted["job_id"], timeout_seconds=3.0)
        assert result["state"] == "outcome_unknown"
        assert result["outcome_unknown"] is True
    finally:
        manager.close()
