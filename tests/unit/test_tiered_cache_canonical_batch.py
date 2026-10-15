"""Deferred tests for the current L2 batch-write contract; no persistent state."""

import pytest

from local_ai_hub.cache import TieredCache


class SingleWriteProvider:
    def __init__(self, coordinator=None):
        self.writes = []
        self._command_cache_coordinator = coordinator

    def set(self, key, value):
        self.writes.append((key, value))


@pytest.mark.parametrize("coordinated", [False, True])
def test_missing_batch_api_rejects_before_any_write_or_coordination(coordinated):
    class ForbiddenCoordinator:
        def locked(self):
            pytest.fail("unsupported provider reached coordinator")

    provider = SingleWriteProvider(ForbiddenCoordinator() if coordinated else None)
    cache = TieredCache(provider)
    cache.l1.set("sentinel", "preserved")

    with pytest.raises(AttributeError, match="set_many"):
        cache.set_many({"new": "value"})

    assert provider.writes == []
    assert cache.l1.get("sentinel") == "preserved"
    assert cache.l1.get("new") is None


def test_noncallable_batch_api_rejects_without_single_writes():
    provider = SingleWriteProvider()
    provider.set_many = None
    cache = TieredCache(provider)

    with pytest.raises(TypeError, match="set_many must be callable"):
        cache.set_many({"new": "value"})

    assert provider.writes == []
    assert cache.l1.get("new") is None


def test_supported_provider_receives_one_batch_and_populates_l1():
    class BatchProvider:
        def __init__(self):
            self.batches = []

        def set_many(self, items):
            self.batches.append(dict(items))

    provider = BatchProvider()
    cache = TieredCache(provider, l1_entries=32)
    values = {"first": 0, "second": False}

    cache.set_many(values)

    assert provider.batches == [values]
    assert cache.l1.get("first") == 0
    assert cache.l1.get("second") is False


def test_empty_batch_has_no_provider_or_l1_side_effects():
    provider = SingleWriteProvider()
    cache = TieredCache(provider)
    cache.l1.set("sentinel", "preserved")

    cache.set_many({})

    assert provider.writes == []
    assert cache.l1.get("sentinel") == "preserved"
