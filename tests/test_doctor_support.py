from __future__ import annotations

from local_ai_hub.doctor_support import probe_hub_status


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
    assert client.paths == ["/v1/live/status?light=1"]
