from __future__ import annotations

import threading

from local_ai_hub.app import _prewarm_route_is_eligible, _runtime_is_available, _wait_for_prewarm_backend


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
