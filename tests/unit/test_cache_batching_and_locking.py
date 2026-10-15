from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub import cache as cache_module
from local_ai_hub.cache import MemoryLRUCache, SQLiteCache, TieredCache, _CommandCacheCoordinator


def test_memory_batching_preserves_none_duplicate_and_expiry_accounting(monkeypatch) -> None:
    now = [10.0]
    monkeypatch.setattr(cache_module.time, "monotonic", lambda: now[0])
    cache = MemoryLRUCache(max_entries=16, ttl_seconds=5, shards=4)
    cache.set_many({"present": "value", "none": None, "expired": "old"})

    assert cache.get_many(["present", "present", "none", "missing"]) == {"present": "value"}
    assert cache.hits == 3
    assert cache.misses == 1
    now[0] = 16.0
    assert cache.get_many(["present", "expired"]) == {}
    assert cache.misses == 3


def test_memory_batching_applies_per_shard_lru_bounds() -> None:
    cache = MemoryLRUCache(max_entries=8, shards=2)
    items = {f"key-{index}": index for index in range(40)}

    cache.set_many(items)

    assert len(cache._items) <= 8
    assert cache.evictions > 0


def test_sqlite_set_many_round_trips_none_and_prunes_to_bound(tmp_path: Path) -> None:
    cache = SQLiteCache(tmp_path / "cache.sqlite", "batch", max_entries=50)
    first = {"none": None, **{f"key-{index}": {"index": index} for index in range(29)}}

    cache.set_many(first)

    assert cache.get_many(list(first)) == first
    overflow = {f"overflow-{index}": index for index in range(40)}
    cache.set_many(overflow)
    assert len(cache.get_many([*first, *overflow])) <= 50
    assert cache.get("none") is None


def test_sqlite_batch_pruning_preserves_capacity_and_newest_entries(tmp_path: Path) -> None:
    cache = SQLiteCache(tmp_path / "small.sqlite", "small", max_entries=2)

    cache.set_many({"old": 1, "middle": 2, "newest": 3})

    retained = cache.get_many(["old", "middle", "newest"])
    assert len(retained) == 2
    assert retained == {"middle": 2, "newest": 3}


def test_sqlite_set_many_rolls_back_partial_executemany_failure(tmp_path: Path) -> None:
    cache = SQLiteCache(tmp_path / "atomic.sqlite", "atomic", max_entries=10)

    cache.set_many({"good-before-error": "value", None: "invalid-null-key"})

    assert cache.get("good-before-error") is None
    assert cache.stats()["entries"] == 0


def test_tiered_batching_promotes_l2_hits_and_preserves_duplicate_counters(tmp_path: Path) -> None:
    l2 = SQLiteCache(tmp_path / "tiered.sqlite", "batch", max_entries=50)
    tiered = TieredCache(l2, l1_entries=64)
    values = {f"key-{index}": index for index in range(10)}
    tiered.set_many(values)
    assert tiered.get_many(["key-0", "key-0", "key-1"]) == {"key-0": 0, "key-1": 1}
    assert tiered.l1_hits == 3

    tiered.l1.clear()
    assert tiered.get_many(["key-0", "key-0", "missing"]) == {"key-0": 0}
    assert tiered.l2_hits == 1
    assert tiered.misses == 2
    assert tiered.get_many(["key-0"]) == {"key-0": 0}
    assert tiered.l1_hits == 4


def test_tiered_batch_write_fails_closed_when_poison_recovery_fails(tmp_path: Path) -> None:
    l2 = SQLiteCache(tmp_path / "poisoned.sqlite", "batch", max_entries=10)
    tiered = TieredCache(l2)

    class PoisonedCoordinator:
        @contextmanager
        def locked(self):
            yield

        def read_locked(self):
            return 7, True

        def write_redundant_locked(self, _generation, _poisoned):
            raise OSError("cannot clear poison marker")

    tiered._coordinator = PoisonedCoordinator()
    tiered.set_many({"not-written": "value"})

    assert l2.get("not-written") is None
    assert tiered.l1.get("not-written") is None
    assert tiered._l1_generation is None


def test_windows_command_cache_lock_timeout_uses_bounded_nonblocking_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = _CommandCacheCoordinator(tmp_path / "cache.sqlite", "windows-test")
    clock = [0.0]
    calls = []

    def lock(_fd, mode, _length):
        calls.append(mode)
        raise OSError("busy")

    fake_msvcrt = SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=lock)
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    class FakeWindowsOS:
        name = "nt"

        def __getattr__(self, name):
            return getattr(os, name)

    monkeypatch.setattr(cache_module, "os", FakeWindowsOS())
    monkeypatch.setattr(cache_module, "_COMMAND_CACHE_LOCK_TIMEOUT_SECONDS", 0.025)
    monkeypatch.setattr(cache_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(cache_module.time, "sleep", lambda duration: clock.__setitem__(0, clock[0] + duration))

    with pytest.raises(TimeoutError, match="coordination lock timed out"):
        with coordinator.locked():
            pytest.fail("contended Windows lock should not be acquired")

    assert calls and set(calls) == {fake_msvcrt.LK_NBLCK}
    assert clock[0] <= 0.035
