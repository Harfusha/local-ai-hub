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
