from __future__ import annotations

from typing import Any

from local_ai_hub.commands import CommandBroker


class _ReadCache:
    def __init__(self, value: Any, healthy: bool) -> None:
        self.value = value
        self.healthy = healthy
        self.keys: list[str] = []

    def get_checked(self, key: str) -> tuple[Any, bool]:
        self.keys.append(key)
        return self.value, self.healthy


def test_unhealthy_success_cache_cannot_fall_through_to_stale_failure_value() -> None:
    success = _ReadCache(None, False)
    failure = _ReadCache({"success": False, "stale": True}, True)

    result = CommandBroker._read_cached_command_result(success, failure, "key")

    assert result is None
    assert success.keys == ["key"]
    assert failure.keys == []


def test_unhealthy_failure_cache_is_a_cache_miss() -> None:
    success = _ReadCache(None, True)
    failure = _ReadCache({"success": False, "stale": True}, False)

    assert CommandBroker._read_cached_command_result(success, failure, "key") is None

def test_unhealthy_suppression_cache_is_miss() -> None:
    suppression = _ReadCache({"success": False, "stale": True}, False)

    assert CommandBroker._read_cache_entry(suppression, "attempt") == (None, False)
