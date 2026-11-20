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


def test_service_start_command_timeout_covers_cold_start_window(monkeypatch):
    module = runpy.run_path(str(Path(__file__).parents[1] / "tools" / "hubctl.py"))
    globals_ = module["_service"].__globals__
    calls = []

    def run(*args, **kwargs):
        calls.append(kwargs["timeout"])
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setitem(globals_, "_startup_wait_seconds", lambda: 125.0)
    monkeypatch.setitem(globals_["subprocess"].__dict__, "run", run)

    assert module["_service"]("start") is True
    assert module["_service"]("stop") is True
    assert calls == [135.0, 35.0]
