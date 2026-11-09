from __future__ import annotations

import threading

from local_ai_hub.app import (
    _prewarm_admission_state,
    _prewarm_route_is_eligible,
    _prewarm_should_retry,
    _runtime_is_available,
    _wait_for_prewarm_backend,
)


class _OfflineRuntime:
    def is_online(self) -> bool:
        return False


def test_prewarm_backend_gate_skips_unavailable_runtime() -> None:
    assert _runtime_is_available(_OfflineRuntime()) is False


def test_prewarm_backend_gate_preserves_unknown_runtime_adapters() -> None:
    assert _runtime_is_available(object()) is True


class _UnavailableLlamaRoute:
    def supports_model(self, _model: str) -> bool:
        return True

    def hardware_enabled(self) -> bool:
        return False


class _ConfiguredRuntime:
    llama_cpp = _UnavailableLlamaRoute()
    config = {"llama_cpp": {"fallback_to_ollama": False}}


def test_prewarm_route_gate_skips_explicitly_unavailable_adapter() -> None:
    assert _prewarm_route_is_eligible(_ConfiguredRuntime(), "qwen2.5-coder:7b") is False


def test_prewarm_route_gate_allows_fallback() -> None:
    runtime = _ConfiguredRuntime()
    runtime.config = {"llama_cpp": {"fallback_to_ollama": True}}
    assert _prewarm_route_is_eligible(runtime, "qwen2.5-coder:7b") is True


def test_prewarm_backend_wait_is_bounded_for_offline_runtime() -> None:
    assert _wait_for_prewarm_backend(_OfflineRuntime(), threading.Event(), 0.0) is False


def test_prewarm_backend_wait_accepts_online_runtime() -> None:
    class _OnlineRuntime:
        def is_online(self) -> bool:
            return True

    assert _wait_for_prewarm_backend(_OnlineRuntime(), threading.Event(), 1.0) is True


def test_prewarm_defers_offline_runtime_start_to_scheduler_admission() -> None:
    class _StartableRuntime:
        ensure_calls = 0

        def is_online(self) -> bool:
            return False

        def ensure_running(self) -> bool:
            self.ensure_calls += 1
            raise AssertionError("prewarm gate must not start runtime outside scheduler admission")

    runtime = _StartableRuntime()

    assert _wait_for_prewarm_backend(runtime, threading.Event(), 0.0) is True
    assert runtime.ensure_calls == 0


def test_prewarm_stops_retrying_after_unknown_gpu_outcome() -> None:
    class _UnknownScheduler:
        def status(self) -> dict[str, str]:
            return {"gpu_admission_state": "outcome_unknown"}

    assert _prewarm_should_retry(_UnknownScheduler()) is False


def test_prewarm_retries_while_gpu_is_temporarily_busy() -> None:
    class _BusyScheduler:
        def status(self) -> dict[str, str]:
            return {"gpu_admission_state": "external_reservation"}

    assert _prewarm_should_retry(_BusyScheduler()) is True


def test_prewarm_stops_when_scheduler_status_is_unavailable_or_unknown() -> None:
    class _UnavailableScheduler:
        def status(self) -> dict[str, str]:
            raise RuntimeError("status unavailable")

    class _UnknownStateScheduler:
        def status(self) -> dict[str, str]:
            return {"gpu_admission_state": "unexpected"}

    assert _prewarm_should_retry(_UnavailableScheduler()) is False
    assert _prewarm_should_retry(_UnknownStateScheduler()) is False


def test_prewarm_stops_when_admission_state_is_not_a_string() -> None:
    class _MalformedScheduler:
        def status(self):
            return {"gpu_admission_state": []}

    assert _prewarm_should_retry(_MalformedScheduler()) is False


def test_prewarm_admission_diagnostic_preserves_unknown_and_unavailable_reasons() -> None:
    class _UnknownScheduler:
        def status(self) -> dict[str, str]:
            return {"gpu_admission_state": "outcome_unknown"}

    class _UnavailableScheduler:
        def status(self) -> dict[str, str]:
            raise RuntimeError("status unavailable")

    class _MalformedScheduler:
        def status(self):
            return {"gpu_admission_state": []}

    assert _prewarm_admission_state(_UnknownScheduler()) == "outcome_unknown"
    assert _prewarm_admission_state(_UnavailableScheduler()) == "status_unavailable"
    assert _prewarm_admission_state(_MalformedScheduler()) == "unknown"


def test_prewarm_failure_is_not_reported_as_recovered(monkeypatch, tmp_path) -> None:
    from local_ai_hub import app as app_module
    from local_ai_hub.scheduler import AffinityScheduler
    from local_ai_hub.telemetry import TelemetryStore

    events = []
    def fail_prewarm(_self, _model):
        raise RuntimeError("simulated prewarm failure")
    def capture_error(_self, component, operation, error, **kwargs):
        if component == "prewarm":
            events.append(kwargs)
    monkeypatch.setattr(AffinityScheduler, "prewarm", fail_prewarm)
    monkeypatch.setattr(AffinityScheduler, "status", lambda _self: {"gpu_admission_state": "outcome_unknown"})
    monkeypatch.setattr(TelemetryStore, "record_error", capture_error)
    monkeypatch.setattr(app_module, "_wait_for_prewarm_backend", lambda *_args: True)
    monkeypatch.setattr(app_module, "_prewarm_route_is_eligible", lambda *_args: True)
    config = tmp_path / "config.toml"
    state = (tmp_path / "state").as_posix()
    config.write_text(
        f'[server]\nstate_dir="{state}"\n[hardware]\nprofile="cpu"\nauto_tune=false\n'
        '[prewarm]\nenabled=true\ndelay_seconds=0\n[preprocessing]\nenabled=false\n'
        '[resilience]\nwatchdog_enabled=false\n[code_intelligence]\nenabled=false\n', encoding="utf-8",
    )
    app = app_module.LocalAIApp(str(config))
    try:
        assert app._prewarm_thread is not None
        app._prewarm_thread.join(timeout=5)
        assert not app._prewarm_thread.is_alive()
        assert len(events) == 1
        assert events[0].get("recovered") is False
    finally:
        app.close()
