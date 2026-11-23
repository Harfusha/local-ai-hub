from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from local_ai_hub import scheduler as scheduler_module
from local_ai_hub.scheduler import AffinityScheduler, Job, SchedulerCancelledError


def _scheduler() -> AffinityScheduler:
    scheduler = object.__new__(AffinityScheduler)
    scheduler._active_model = "active-model"
    scheduler.max_other_wait = 10.0
    scheduler._last_switch = 0.0
    scheduler.switch_cooldown = 0.0
    scheduler.batch_jobs = 0
    scheduler._active_dispatched = 1
    scheduler.batch_seconds = 0.0
    scheduler._active_since = 0.0
    scheduler.background_switch_grace = 0.0
    scheduler._last_foreground_activity = 0.0
    return scheduler


def _job(
    job_id: int,
    model: str,
    priority: int,
    created_at: float,
    *,
    background: bool = False,
) -> Job:
    return Job(
        id=job_id,
        model=model,
        source="test",
        priority=priority,
        execute=lambda: {"success": True},
        background=background,
        created_at=created_at,
    )


@pytest.mark.parametrize("interruption", ["failed", "cancelled", "rejected"])
def test_cold_model_penalty_learns_only_from_successful_switches(tmp_path, monkeypatch, interruption):
    clock = [0.0]

    def prepare_model(model, **_kwargs):
        if model == "baseline":
            clock[0] += 3.0
        elif model == "slow":
            clock[0] += 93.0
        else:
            clock[0] += 120.0
            error = RuntimeError(interruption)
            error.operation_not_started = True
            if interruption == "cancelled":
                error.preparation_cancelled = True
            elif interruption == "rejected":
                error.admission = {"state": "rejected", "reason": "fixture capacity"}
            raise error
        return []

    runtime = SimpleNamespace(loaded_models=lambda: ["warm"], loaded_model_details=lambda: [], prepare_model=prepare_model)
    scheduler = AffinityScheduler(runtime, {"server": {"state_dir": str(tmp_path)}})
    jobs = [_job(1, "cold", priority=6, created_at=100.0), _job(2, "warm", priority=5, created_at=100.0)]
    try:
        original_time = scheduler_module.time
        with monkeypatch.context() as measured:
            measured.setattr(scheduler_module, "time", SimpleNamespace(
                perf_counter=lambda: clock[0], monotonic=original_time.monotonic, time=original_time.time,
                sleep=original_time.sleep,
            ))
            assert scheduler._perform_switch("baseline")
            assert scheduler._choose_initial_model(jobs, now=100.0) == "cold"
            assert not scheduler._perform_switch("interrupted")
            assert scheduler._stats["switch_time_ms"] == 123_000.0
            assert scheduler._choose_initial_model(jobs, now=100.0) == "cold"

            assert scheduler._perform_switch("slow")
            assert scheduler._choose_initial_model(jobs, now=100.0) == "warm"
            urgent = [_job(3, "warm", priority=1, created_at=100.0), _job(4, "cold", priority=9, created_at=100.0)]
            assert scheduler._choose_initial_model(urgent, now=100.0) == "cold"
    finally:
        scheduler.close()


def test_initial_inventory_does_not_block_queue_or_reuse_cancelled_selection(tmp_path):
    inventory_started, release_inventory, cancel = Event(), Event(), Event()
    prepared = []

    def loaded_models():
        inventory_started.set()
        assert release_inventory.wait(8)
        return ["cancelled-model"]

    def prepare_model(model, **_kwargs):
        prepared.append(model)
        return []

    runtime = SimpleNamespace(loaded_models=loaded_models, loaded_model_details=lambda: [], prepare_model=prepare_model)
    scheduler = AffinityScheduler(runtime, {"server": {"state_dir": str(tmp_path)}})
    try:
        with ThreadPoolExecutor(max_workers=2) as callers:
            try:
                first = callers.submit(scheduler.submit, "cancelled-model", source="test", execute=lambda: {"success": True},
                                       wait_timeout=5, cancel_event=cancel)
                assert inventory_started.wait(3)
                cancel.set()
                with pytest.raises(SchedulerCancelledError):
                    first.result(timeout=1.5)

                replacement = callers.submit(scheduler.enqueue, "replacement", source="test", execute=lambda: {"success": True},
                                             priority=5, background=False).result(timeout=1.5)
                assert not replacement.done.is_set()
            finally:
                release_inventory.set()

        assert replacement.done.wait(3)
        assert replacement.result["success"] is True
        assert prepared == ["replacement"]
    finally:
        scheduler.close()


def test_foreground_priority_ages_and_caps_at_nine() -> None:
    scheduler = _scheduler()
    old = _job(1, "active-model", priority=7, created_at=0.0)
    new = _job(2, "active-model", priority=8, created_at=89.0)

    selected = scheduler._choose_job_for_active_model(now=90.0, jobs=[new, old])

    assert selected is old


def test_background_priority_does_not_age() -> None:
    scheduler = _scheduler()
    scheduler.background_allowed = lambda **_kwargs: True
    old = _job(1, "active-model", priority=1, created_at=0.0, background=True)
    new = _job(2, "active-model", priority=2, created_at=900.0, background=True)

    selected = scheduler._choose_job_for_active_model(now=1000.0, jobs=[old, new])

    assert selected is new


@pytest.mark.parametrize(("background", "expected"), [(False, "old"), (True, "new")])
def test_initial_model_ages_only_foreground_priority(background: bool, expected: str) -> None:
    scheduler = _scheduler()
    scheduler._stats = {}
    old = _job(1, "old", priority=1, created_at=0.0, background=background)
    new = _job(2, "new", priority=2, created_at=990.0, background=background)

    assert scheduler._choose_initial_model([old, new], now=1000.0, loaded_models=set()) == expected


def test_starved_foreground_model_forces_switch_but_background_does_not() -> None:
    scheduler = _scheduler()
    active = _job(1, "active-model", priority=1, created_at=95.0)
    starved = _job(2, "other-model", priority=1, created_at=90.0)

    assert not scheduler._should_switch(now=99.0, jobs=[active, starved])
    assert scheduler._should_switch(now=100.0, jobs=[active, starved])
    assert scheduler._choose_next_model(
        [active, starved], exclude="active-model", now=100.0
    ) == "other-model"

    old_background = _job(3, "background-model", priority=9, created_at=0.0, background=True)
    assert not scheduler._should_switch(now=100.0, jobs=[active, old_background])
