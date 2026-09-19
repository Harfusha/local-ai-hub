from __future__ import annotations

import runpy
from pathlib import Path


def test_managed_start_waits_for_cold_start_without_direct_spawn(monkeypatch):
    module = runpy.run_path(str(Path(__file__).parents[1] / "tools" / "hubctl.py"))
    globals_ = module["start"].__globals__
    calls = {"ensure": 0}
    clock = {"now": 0.0}

    class Client:
        def _online(self):
            return clock["now"] >= 45.0

        def ensure_server(self):
            calls["ensure"] += 1
            return False

    monkeypatch.setitem(globals_, "_service", lambda _action: True)
    monkeypatch.setitem(globals_, "client", Client)
    monkeypatch.setitem(globals_, "_startup_wait_seconds", lambda: 60.0)
    monkeypatch.setitem(globals_["time"].__dict__, "time", lambda: clock["now"])
    monkeypatch.setitem(globals_["time"].__dict__, "sleep", lambda seconds: clock.__setitem__("now", clock["now"] + seconds))

    assert module["start"]() is True
    assert calls["ensure"] == 0


def test_graceful_stop_requests_service_shutdown(monkeypatch):
    module = runpy.run_path(str(Path(__file__).parents[1] / "tools" / "service.py"))
    calls = []
    online = {"value": True}

    class Client:
        def __init__(self, **_kwargs):
            pass

        def _online(self):
            current = online["value"]
            online["value"] = False
            return current

        def request(self, path, payload, **kwargs):
            calls.append((path, payload, kwargs))
            return {"success": True}

    globals_ = module["request_graceful_hub_stop"].__globals__
    monkeypatch.setitem(globals_, "HubClient", Client)
    monkeypatch.setitem(globals_["time"].__dict__, "monotonic", lambda: 0.0)
    monkeypatch.setitem(globals_["time"].__dict__, "sleep", lambda _seconds: None)

    assert module["request_graceful_hub_stop"]() is True
    assert calls == [("/api/control", {"action": "stop_service"}, {"timeout": 2.0, "replay_safe": False})]


def test_graceful_stop_falls_back_when_hub_offline(monkeypatch):
    module = runpy.run_path(str(Path(__file__).parents[1] / "tools" / "service.py"))

    class Client:
        def __init__(self, **_kwargs):
            pass

        def _online(self):
            return False

    monkeypatch.setitem(module["request_graceful_hub_stop"].__globals__, "HubClient", Client)
    assert module["request_graceful_hub_stop"]() is False
