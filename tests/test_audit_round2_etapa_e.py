from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from local_ai_hub.agent_routing import RoutingEngine
from local_ai_hub.agent_verification import ChangeIntent
from local_ai_hub.scheduler import AffinityScheduler, Job


@pytest.fixture
def affinity_scheduler(tmp_path):
    runtime = SimpleNamespace(
        loaded_models=lambda: ["resident-model"],
        loaded_model_details=lambda: [],
    )
    scheduler = AffinityScheduler(runtime, {"server": {"state_dir": str(tmp_path)}})
    try:
        yield scheduler
    finally:
        scheduler.close()


def test_n08_scheduler_does_not_starve_high_priority_for_resident_model(affinity_scheduler):
    now = time.monotonic()

    # High priority urgent job for un-loaded model
    urgent_job = Job(id=1, model="urgent-model", source="test", priority=9, execute=lambda: {}, created_at=now - 1.0)
    # Low priority job for currently resident model
    low_job = Job(id=2, model="resident-model", source="test", priority=1, execute=lambda: {}, created_at=now)

    chosen = affinity_scheduler._choose_initial_model([urgent_job, low_job], now)
    assert chosen == "urgent-model", f"High priority model was starved by resident model: chosen was {chosen}"


def test_n08_measured_switch_cost_can_outweigh_small_priority_gap(affinity_scheduler):
    affinity_scheduler._stats.update(model_switches=1, successful_switch_time_ms=120_000.0)
    now = time.monotonic()
    urgent_job = Job(
        id=1, model="urgent-model", source="test", priority=8,
        execute=lambda: {}, created_at=now,
    )
    resident_job = Job(
        id=2, model="resident-model", source="test", priority=5,
        execute=lambda: {}, created_at=now,
    )

    assert affinity_scheduler._choose_initial_model([urgent_job, resident_job], now) == "resident-model"


def test_n08_wait_bonus_can_recover_switch_penalty(affinity_scheduler):
    affinity_scheduler._stats.update(model_switches=1, successful_switch_time_ms=120_000.0)
    now = time.monotonic()
    resident_job = Job(
        id=1, model="resident-model", source="test", priority=4,
        execute=lambda: {}, created_at=now,
    )
    waiting_job = Job(
        id=2, model="cold-model", source="test", priority=1,
        execute=lambda: {}, created_at=now - 240.0,
    )

    assert affinity_scheduler._choose_initial_model([resident_job, waiting_job], now) == "cold-model"


def test_n23_routing_engine_multi_language_test_selection():
    engine = RoutingEngine()
    change = ChangeIntent.create(
        task_id="t-1",
        affected_paths=[
            "src/components/button.tsx",
            "pkg/api/handler.go",
            "src/auth/token.rs",
            "src/utils.py",
        ],
    )
    sel = engine.select_tests(change)
    tests = list(sel.selected_tests)

    assert "tests/button.test.ts" in tests, f"TypeScript test missing: {tests}"
    assert "pkg/api/handler_test.go" in tests, f"Go test missing: {tests}"
    assert "tests/token_test.rs" in tests, f"Rust test missing: {tests}"
    assert "tests/test_utils.py" in tests, f"Python test missing: {tests}"
