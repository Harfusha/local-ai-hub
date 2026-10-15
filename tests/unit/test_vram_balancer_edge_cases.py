"""Deferred source integration regressions; no GPU sampling or model calls."""
import pytest

from local_ai_hub.vram_balancer import VRAMBalancer


@pytest.mark.parametrize("model,ttl", [
    ("", 1), ("  ", 1), (None, 1), ("fake", 0), ("fake", -1), ("fake", True),
    ("fake", float("nan")), ("fake", float("inf")), ("fake", None),
])
def test_invalid_pin_inputs_preserve_existing_pin(model, ttl):
    balancer = VRAMBalancer()
    balancer.pin_model("existing", 10)
    before = (balancer._pinned_model, balancer._pin_expires, balancer._status_generation)
    with pytest.raises(ValueError):
        balancer.pin_model(model, ttl)
    assert (balancer._pinned_model, balancer._pin_expires, balancer._status_generation) == before


@pytest.mark.parametrize("base", [64, 1024, 2048, 4096, 8192, 32768])
@pytest.mark.parametrize("factor", [0, 0.25, 0.5, 1, 2, -1, float("nan"), float("inf"), None, "invalid"])
def test_context_recommendation_never_exceeds_requested_window(monkeypatch, base, factor):
    balancer = VRAMBalancer()
    monkeypatch.setattr(balancer, "status", lambda: {"context_budget_factor": factor})
    assert 1 <= balancer.recommended_context_budget(base) <= base


@pytest.mark.parametrize("base", [0, -1, True, "4096", 1.5])
def test_invalid_context_request_fails_before_hardware_sampling(monkeypatch, base):
    balancer = VRAMBalancer()
    monkeypatch.setattr(balancer, "status", lambda: pytest.fail("invalid request sampled GPU"))
    with pytest.raises(ValueError):
        balancer.recommended_context_budget(base)
