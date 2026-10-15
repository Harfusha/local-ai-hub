"""Deferred safe adaptation of gemini/wave-8-task-86 circuit bounds."""
import pytest

from local_ai_hub import resilience
from local_ai_hub.resilience import CircuitBreakerRegistry


def test_capacity_never_evicts_open_circuit_or_creates_unbounded_success_keys(monkeypatch):
    tick = [10.0]
    monkeypatch.setattr(resilience.time, "monotonic", lambda: tick[0])
    registry = CircuitBreakerRegistry(failure_threshold=1, cooldown_seconds=20, max_breakers=1)
    assert registry.allow("existing")
    registry.failure("existing")
    for number in range(100):
        key = f"untracked-{number}"
        assert not registry.allow(key)
        registry.success(key)
        registry.failure(key)
    assert list(registry.status()) == ["existing"]
    assert registry.status()["existing"]["open"]
    assert not registry.allow("existing")


def test_existing_resource_recovers_at_capacity_without_losing_probe_ownership(monkeypatch):
    tick = [10.0]
    monkeypatch.setattr(resilience.time, "monotonic", lambda: tick[0])
    registry = CircuitBreakerRegistry(failure_threshold=1, cooldown_seconds=1, probe_timeout_seconds=2, max_breakers=1)
    registry.failure("existing")
    tick[0] = 12
    assert registry.allow("existing")
    assert not registry.allow("existing")
    assert not registry.allow("unknown")
    tick[0] = 15
    assert not registry.status()["existing"]["half_open_probe"]
    assert registry.allow("existing")
    registry.success("existing")
    assert registry.allow("existing")
    assert not registry.status()["existing"]["open"]


@pytest.mark.parametrize("key", ["", " ", None, 1, "x" * 513])
@pytest.mark.parametrize("operation", ["allow", "success", "failure"])
def test_invalid_key_never_allocates_state(key, operation):
    registry = CircuitBreakerRegistry()
    with pytest.raises(ValueError):
        getattr(registry, operation)(key)
    assert registry.status() == {}
