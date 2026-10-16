import pytest
from pathlib import Path

from local_ai_hub.cache import (
    _CommandCacheCoordinator,
    SQLiteCache,
    MemoryLRUCache,
    TieredCache,
)


def test_command_cache_coordinator_validation():
    with pytest.raises(ValueError, match="invalid cache path"):
        _CommandCacheCoordinator("bad\x00path", "ns")

    with pytest.raises(ValueError, match="invalid cache namespace"):
        _CommandCacheCoordinator(Path("valid/path"), "bad\x00ns")


def test_sqlite_cache_validation(tmp_path: Path):
    with pytest.raises(ValueError, match="invalid cache path"):
        SQLiteCache("bad\x00path", "ns")

    with pytest.raises(ValueError, match="invalid cache namespace"):
        SQLiteCache(tmp_path / "cache.sqlite3", "bad\x00ns")

    cache = SQLiteCache(tmp_path / "cache.sqlite3", "test_ns")

    # Invalid null-byte keys
    assert cache.get("key\x00bad") is None
    assert cache.get("") is None
    cache.set("key\x00bad", "val")
    cache.set("", "val")
    assert cache.get("key\x00bad") is None


def test_memory_lru_cache_boolean_guard():
    cache = MemoryLRUCache(max_entries=True, ttl_seconds=False)
    assert cache.max_entries >= 1
    assert cache.ttl_seconds >= 0.0


def test_tiered_cache_boolean_guard(tmp_path: Path):
    l2 = SQLiteCache(tmp_path / "l2.sqlite3", "tiered_ns")
    tiered = TieredCache(l2, l1_entries=True, l1_ttl_seconds=False)
    assert tiered.l1.max_entries >= 1
