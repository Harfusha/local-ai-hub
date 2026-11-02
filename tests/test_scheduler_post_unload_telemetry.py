from types import SimpleNamespace

import pytest

from local_ai_hub.scheduler import AffinityScheduler
from local_ai_hub.vram_balancer import VRAMBalancer


@pytest.mark.parametrize("active_model", [None, "target-model"])
def test_mixed_backend_requires_admission_for_initial_or_same_name_switch(active_model):
    import threading
    from collections import Counter

    calls = []
    class Runtime:
        def supports_post_unload_admission(self, _model):
            return True
        def requires_post_unload_admission(self, _model):
            return True
        def resource_status(self):
            return {"available": True, "vram_total_mb": 8192, "vram_available_mb": 6144}
        def loaded_model_details(self):
            return []
        def prepare_model(self, _model, *, post_unload_admission, **_kwargs):
            calls.append(post_unload_admission()["state"])
            return []

    scheduler = object.__new__(AffinityScheduler)
    scheduler.runtime = Runtime()
    scheduler.config = {"scheduler": {"model_vram_estimates_bytes": {"target-model": 1024**3}}}
    scheduler._cond = threading.Condition()
    scheduler._pending = []
    scheduler._model_vram_bytes = {}
    scheduler._active_model = active_model
    scheduler._active_since = 1.0
    scheduler._active_dispatched = 0
    scheduler._last_switch = 0.0
    scheduler._switch_sequence = 0
    scheduler._stats = Counter()
    scheduler._model_blocked_until = {}
    scheduler._model_last_error = {}
    scheduler.switch_failure_cooldown = 1.0
    scheduler.unload_others = True
    assert scheduler._perform_switch("target-model") is True
    assert calls == ["admitted"]


def test_required_mixed_admission_fails_closed_without_telemetry():
    import threading
    from collections import Counter

    calls = []
    runtime = SimpleNamespace(requires_post_unload_admission=lambda _model: True,
                              supports_post_unload_admission=lambda _model: True,
                              loaded_model_details=lambda: [],
                              prepare_model=lambda *_a, **_kw: calls.append("load"))
    scheduler = object.__new__(AffinityScheduler)
    scheduler.runtime, scheduler.config = runtime, {}
    scheduler._cond = threading.Condition()
    scheduler._pending = []
    scheduler._model_vram_bytes = {}
    scheduler._active_model = None
    scheduler._active_since = 1.0
    scheduler._active_dispatched = 0
    scheduler._last_switch = 0.0
    scheduler._switch_sequence = 0
    scheduler._stats = Counter()
    scheduler._model_blocked_until = {}
    scheduler._model_last_error = {}
    scheduler.switch_failure_cooldown = 1.0
    scheduler.unload_others = True
    assert scheduler._perform_switch("target-model") is False
    assert calls == []


def scheduler_with_balancer(balancer):
    scheduler = object.__new__(AffinityScheduler)
    scheduler.runtime = SimpleNamespace(vram_balancer=balancer)
    scheduler.config = {
        "scheduler": {"model_vram_estimates_bytes": {"target-model": 1024**3}},
    }
    scheduler._model_vram_bytes = {}
    return scheduler


def test_post_unload_waits_for_actual_balancer_sample(monkeypatch):
    import local_ai_hub.vram_balancer as module

    monkeypatch.setattr(module, "get_gpu_telemetry", lambda: {
        "available": True, "gpu_name": "Test GPU", "vendor": "nvidia",
        "vram_total_mb": 8192.0, "vram_used_mb": 2048.0,
        "vram_available_mb": 6144.0,
    })
    scheduler = scheduler_with_balancer(VRAMBalancer())

    result = scheduler._post_unload_vram_admission("target-model")

    assert result["state"] == "admitted"
    assert result["vram_available_bytes"] == 6144 * 1024**2


@pytest.mark.parametrize("sample", [
    {"available": False, "vram_total_mb": 8192.0, "vram_available_mb": 6144.0},
    {"available": False},
    {"available": "false", "vram_total_mb": 8192.0, "vram_available_mb": 6144.0},
    {"vram_total_mb": 8192.0, "vram_available_mb": 6144.0},
])
def test_post_unload_rejects_explicitly_unavailable_measurement(sample):
    class Balancer:
        def status(self, force=False):
            return dict(sample)

    result = scheduler_with_balancer(Balancer())._post_unload_vram_admission("target-model")

    assert result["state"] == "rejected"
    assert result["reason"] == "post_unload_vram_unavailable"


def test_post_unload_requests_refresh_without_changing_normal_status():
    calls = []

    class Balancer:
        def status(self, force=False):
            calls.append(force)
            return {"available": False}

    scheduler = scheduler_with_balancer(Balancer())
    scheduler._resource_status()
    scheduler._post_unload_vram_admission("target-model")

    assert calls == [False, True]
