from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("operation", ["load", "release", "count", "registered"])
def test_cuda_lifecycle_lock_acquisition_is_bounded(monkeypatch, operation):
    import local_ai_hub.model_lifecycle as module
    calls = []
    class Lock:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def acquire(self, *, timeout):
            calls.append(timeout)
            return False
        def release(self):
            pytest.fail("unacquired lock must not be released")
    monkeypatch.setattr(module, "_CUDA_MODEL_LOCK", Lock())
    class Owner:
        pass
    owner = Owner()
    factory_calls = []
    with pytest.raises(TimeoutError):
        if operation == "load":
            module.load_model(owner, uses_cuda=True, factory=lambda: factory_calls.append(True))
        elif operation == "release":
            module.release_model(owner, used_cuda=True)
        elif operation == "count":
            module.active_cuda_model_count()
        else:
            module.is_cuda_model_registered(owner)
    assert calls and all(0 <= value <= 5 for value in calls)
    assert factory_calls == []


def test_telemetry_flush_does_not_equate_abandoned_records_with_durable_records():
    from local_ai_hub.telemetry import TelemetryStore
    store = object.__new__(TelemetryStore)
    store.enabled = True
    store._stats_lock = threading.Lock()
    store._stats = {"queued": 2, "processed": 2, "written": 1, "lost_after_acceptance": 1}
    assert store.flush(timeout=0.05) is False


def test_application_close_retries_failed_components_without_reclosing_completed_ones(monkeypatch):
    import local_ai_hub.app as module
    calls = {}
    def close(name, fail_once=False):
        def callback(*args, **kwargs):
            calls[name] = calls.get(name, 0) + 1
            if fail_once and calls[name] == 1:
                raise RuntimeError("controlled component failure")
        return callback
    app = object.__new__(module.LocalAIApp)
    app._close_lock = threading.Lock()
    app._closed = False
    app._shutdown = threading.Event()
    app._prewarm_thread = app._watchdog_thread = None
    app.services = SimpleNamespace(close_lint_daemons=close("lint"), close_context_warmup=close("warmup"))
    app._status_dependency_executor = SimpleNamespace(shutdown=close("status"))
    for name in ("recovery", "preprocessor", "external_tools", "work_orchestrator", "async_jobs", "background_gpu", "scheduler", "telemetry", "deterministic", "code_index"):
        setattr(app, name, SimpleNamespace(close=close(name, name == "preprocessor")))
    app.logger = SimpleNamespace(error=close("error_log"))
    monkeypatch.setattr(module, "shutdown_logging", close("logging"))
    app.close()
    app.close()
    assert calls["preprocessor"] == 2
    assert calls["scheduler"] == 1
    assert app.close_report["success"] is True
