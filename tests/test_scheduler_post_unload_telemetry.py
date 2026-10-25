from types import SimpleNamespace

import pytest

from local_ai_hub.scheduler import AffinityScheduler
from local_ai_hub.vram_balancer import VRAMBalancer


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
