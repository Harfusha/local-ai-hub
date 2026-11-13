from __future__ import annotations

from local_ai_hub.scheduler import AffinityScheduler, Job


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
