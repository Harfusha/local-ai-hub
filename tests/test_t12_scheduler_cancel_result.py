from __future__ import annotations

import threading
import time

import pytest

from local_ai_hub.scheduler import AffinityScheduler, Job


def test_cancelled_switch_returns_false_and_clears_stale_active_model() -> None:
    scheduler = AffinityScheduler.__new__(AffinityScheduler)
    scheduler._cond = threading.Condition()
    scheduler._pending = []
    scheduler._stats = {
        "switch_time_ms": 0.0,
        "evictions": 0,
        "cancelled_pending": 0,
    }
    scheduler._switch_sequence = 0
    scheduler._active_dispatched = 1
    scheduler._active_model = "resident-model"
    scheduler._active_since = 1.0
    scheduler._last_switch = 0.0
    scheduler._switching = True
    scheduler._model_vram_bytes = {}
    scheduler.unload_others = True

    result = scheduler._perform_switch("target-model", should_stop=lambda: True)

    assert result is False
    assert scheduler._active_model is None
    assert scheduler._active_since == 0.0
    assert scheduler._stats["model_switch_cancellations"] == 1


@pytest.mark.parametrize("stopped", ["cancelled", "timed_out"])
def test_stopped_dispatched_job_does_not_start_execute_and_releases_capacity(stopped, monkeypatch) -> None:
    started: list[bool] = []
    cancel = threading.Event()
    if stopped == "cancelled":
        cancel.set()
    job = Job(
        id=1,
        model="fixture-model",
        source="test",
        priority=5,
        execute=lambda: (started.append(True) or {"success": True}),
        cancel_event=cancel,
        deadline=time.monotonic() - 1 if stopped == "timed_out" else None,
        gpu_capacity_lease={"lease_id": "test-lease", "owner": "test-job", "generation": "test-generation"},
    )
    scheduler = AffinityScheduler.__new__(AffinityScheduler)
    scheduler._cond = threading.Condition()
    scheduler._stats = {"completed": 0, "failed": 0, "background_completed": 0, "background_failed": 0}
    scheduler._inflight = 1
    scheduler._inflight_jobs = {job.id: job}
    scheduler._inflight_background = 0
    scheduler._last_foreground_activity = 0.0
    released = []

    def release_capacity(*identity):
        released.append(identity)
        return True

    monkeypatch.setattr(scheduler, "release_gpu_capacity_lease", release_capacity)

    scheduler._run_job(job)

    assert started == []
    assert job.done.is_set()
    assert job.result[stopped] is True and job.result["operation_not_started"] is True
    assert released == [("test-lease", "test-job", "test-generation")]
    assert job.gpu_capacity_lease is None
