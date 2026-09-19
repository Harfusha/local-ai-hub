from __future__ import annotations

from local_ai_hub.app import _runtime_is_available


class _OfflineRuntime:
    def is_online(self) -> bool:
        return False


def test_prewarm_backend_gate_skips_unavailable_runtime() -> None:
    assert _runtime_is_available(_OfflineRuntime()) is False


def test_prewarm_backend_gate_preserves_unknown_runtime_adapters() -> None:
    assert _runtime_is_available(object()) is True
