from __future__ import annotations

from local_ai_hub.doctor_support import installed_models_from_status, probe_hub_status


class _StatusUnavailableClient:
    def __init__(self):
        self.paths: list[str] = []

    def _online(self):
        return True

    def get(self, path, timeout=15):
        self.paths.append(path)
        raise TimeoutError("status read timed out")


def test_doctor_keeps_hub_online_when_health_passes_but_status_times_out():
    client = _StatusUnavailableClient()
    probe = probe_hub_status(client)

    assert probe["hub_online"] is True
    assert probe["status_available"] is False
    assert probe["status"] == {}
    assert client.paths == ["/api/live/status?light=1"]


def test_doctor_falls_back_to_runtime_model_inventory_when_status_is_empty():
    class Runtime:
        def installed_models(self):
            return ["qwen3.5:9b", "qwen3-vl:4b"]

    models = installed_models_from_status({}, runtime_factory=lambda _cfg: Runtime(), cfg={})

    assert models == {"qwen3.5:9b", "qwen3-vl:4b"}
