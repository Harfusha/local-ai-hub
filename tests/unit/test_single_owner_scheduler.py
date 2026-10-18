"""Scheduler contracts have one queue and no caller-selected tenant partition."""

import pytest

from local_ai_hub.scheduler import AffinityScheduler, Job
from local_ai_hub.ollama import OllamaRuntime


@pytest.mark.parametrize("method", ("submit", "enqueue"))
def test_scheduler_rejects_retired_tenant_keyword_before_dispatch(method):
    scheduler = object.__new__(AffinityScheduler)
    with pytest.raises(TypeError, match="tenant"):
        getattr(scheduler, method)("model", source="test", execute=lambda: {}, tenant="retired")


@pytest.mark.parametrize("method", ("submit", "enqueue"))
def test_scheduler_rejects_retired_positional_contract_before_dispatch(method):
    scheduler = object.__new__(AffinityScheduler)
    with pytest.raises(TypeError):
        getattr(scheduler, method)("model", "retired", "test", lambda: {})


@pytest.mark.parametrize("key", ("max_queued_per_tenant", "max_inflight_per_tenant"))
def test_scheduler_rejects_retired_quota_before_starting_threads(key):
    with pytest.raises(ValueError, match="removed.*single local owner"):
        AffinityScheduler(object(), {"scheduler": {key: 1}})


def test_scheduler_preserves_priority_then_age_without_tenant_identity():
    scheduler = object.__new__(AffinityScheduler)
    scheduler._active_model = "model"
    oldest = Job(id=1, model="model", source="test", priority=4, execute=lambda: {}, created_at=10.0)
    newer = Job(id=2, model="model", source="test", priority=4, execute=lambda: {}, created_at=11.0)
    urgent = Job(id=3, model="model", source="test", priority=5, execute=lambda: {}, created_at=12.0)
    assert scheduler._choose_job_for_active_model(13.0, [newer, oldest, urgent]) is urgent
    assert scheduler._choose_job_for_active_model(13.0, [newer, oldest]) is oldest


def test_job_rejects_retired_tenant_field():
    with pytest.raises(TypeError, match="tenant"):
        Job(id=1, model="model", source="test", priority=5, execute=lambda: {}, tenant="retired")


@pytest.mark.parametrize("location", ("inputs", "item"))
@pytest.mark.parametrize("value", (None, "", "retired", False))
def test_benchmark_scenario_rejects_retired_tenant_before_dispatch(location, value):
    runtime = object.__new__(OllamaRuntime)
    runtime.config = {}
    inputs = {"model": "model", "profile": "balanced", "items": [{"id": "one", "prompt": "Return OK"}]}
    target = inputs if location == "inputs" else inputs["items"][0]
    target["tenant"] = value
    result = runtime.run_benchmark_scenario(
        name="scheduler",
        contract={"scenario": "scheduler", "required_fields": ["queue_wait_ms"], "scenario_inputs": inputs},
        scheduler=object(),
    )
    assert result["success"] is False
    assert result["error_type"] == "retired_scenario_field"
