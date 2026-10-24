"""Acceptance coverage for LocalAIApp.close phase reporting and retries."""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest


COMPONENT_PHASES = (
    "recovery", "preprocessor", "external_tools", "work_orchestrator",
    "async_jobs", "background_gpu", "scheduler", "telemetry",
    "deterministic", "code_index",
)
CLOSE_PHASES = (
    "lint_daemons", "context_warmup", "status_dependencies", "helper_threads",
    *COMPONENT_PHASES, "logging",
)


class _HelperThread:
    def __init__(self, fail_first_join: bool):
        self.alive = True
        self.fail_first_join = fail_first_join
        self.join_calls = 0
        self.timeouts = []
        self.name = "bounded-close-test-helper"

    def is_alive(self):
        return self.alive

    def join(self, timeout=None):
        self.join_calls += 1
        self.timeouts.append(timeout)
        if self.fail_first_join and self.join_calls == 1:
            raise OSError("controlled helper join failure")
        self.alive = False


def _app_with_faulty_phase(monkeypatch, failing_phase):
    import local_ai_hub.app as app_module

    calls = {phase: 0 for phase in CLOSE_PHASES}

    def callback(phase):
        def close(*_args, **_kwargs):
            calls[phase] += 1
            if phase == failing_phase and calls[phase] == 1:
                raise OSError(f"controlled {phase} cleanup failure")
        return close

    app = object.__new__(app_module.LocalAIApp)
    app._close_lock = threading.Lock()
    app._closed = False
    app._shutdown = threading.Event()
    helper = _HelperThread(failing_phase == "helper_threads")
    app._prewarm_thread = helper
    app._watchdog_thread = None
    app.services = SimpleNamespace(
        close_lint_daemons=callback("lint_daemons"),
        close_context_warmup=callback("context_warmup"),
    )
    app._status_dependency_executor = SimpleNamespace(shutdown=callback("status_dependencies"))
    for phase in COMPONENT_PHASES:
        setattr(app, phase, SimpleNamespace(close=callback(phase)))
    app.logger = SimpleNamespace(error=lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_module, "shutdown_logging", callback("logging"))
    return app, calls, helper


@pytest.mark.parametrize("phase", CLOSE_PHASES)
def test_app_close_reports_each_phase_failure_then_retries_only_that_phase(monkeypatch, phase):
    app, calls, helper = _app_with_faulty_phase(monkeypatch, phase)

    app.close(timeout=1.0)
    first = app.close_report
    assert first["success"] is False
    assert first["failed"] == [phase]
    assert first["pending"] == []
    assert first["components"][phase]["state"] == "failed"
    assert all(
        detail["state"] == ("failed" if name == phase else "completed")
        for name, detail in first["components"].items()
    )

    coordinator = app._close_coordinator
    app.close(timeout=1.0)
    second = app.close_report
    assert second["success"] is True
    assert second["failed"] == []
    assert second["pending"] == []
    assert all(detail["state"] == "completed" for detail in second["components"].values())
    assert app._close_coordinator is coordinator
    assert all(
        calls[name] == (2 if name == phase else 1)
        for name in CLOSE_PHASES if name != "helper_threads"
    )
    if phase == "helper_threads":
        assert helper.join_calls == 2
        assert all(timeout is None or 0 <= timeout <= 1.5 for timeout in helper.timeouts)


def test_app_close_does_not_duplicate_an_inflight_cleanup_owner(monkeypatch):
    import local_ai_hub.app as app_module

    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def blocked_close():
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(1.0)

    app = object.__new__(app_module.LocalAIApp)
    app._close_lock = threading.Lock()
    app._closed = False
    app._shutdown = threading.Event()
    app._prewarm_thread = app._watchdog_thread = None
    app.services = SimpleNamespace(
        close_lint_daemons=blocked_close,
        close_context_warmup=lambda: None,
    )
    app._status_dependency_executor = SimpleNamespace(shutdown=lambda **_kwargs: None)
    for phase in COMPONENT_PHASES:
        setattr(app, phase, SimpleNamespace(close=lambda: None))
    app.logger = SimpleNamespace(error=lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_module, "shutdown_logging", lambda: None)

    app.close(timeout=0.0)
    try:
        assert entered.wait(0.5)
        assert app.close_report["success"] is False
        app.close(timeout=0.0)
        assert calls == 1
        assert app.close_report["components"]["lint_daemons"]["state"] == "running"
        assert set(app.close_report["pending"]) == set(CLOSE_PHASES)
    finally:
        release.set()
        app.close(timeout=1.0)

    assert app.close_report["success"] is True
    assert calls == 1
