from __future__ import annotations

import threading

from local_ai_hub.app import (
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
