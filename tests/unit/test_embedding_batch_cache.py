import sqlite3
import pytest
from pathlib import Path
from local_ai_hub.cache import SQLiteCache, TieredCache, MemoryLRUCache

def test_sqlite_cache_get_many_single_query(tmp_path: Path):
    db_path = tmp_path / "cache.sqlite3"
    cache = SQLiteCache(db_path, "test_ns")
    
    # Insert multiple items
    cache.set("k1", {"val": 1})
    cache.set("k2", {"val": 2})
    cache.set("k3", {"val": 3})
    
    
    # Test get_many
    res = cache.get_many(["k1", "k2", "k3", "missing"])
    assert res == {
        "k1": {"val": 1},
        "k2": {"val": 2},
        "k3": {"val": 3},
    }

def test_tiered_cache_get_many(tmp_path: Path):
    db_path = tmp_path / "tiered.sqlite3"
    l2 = SQLiteCache(db_path, "tiered_ns")
    cache = TieredCache(l2, l1_entries=10)
    
    # Store directly in L2
    l2.set("k1", "v1")
    l2.set("k2", "v2")
    
    # Store in L1 directly
    cache.l1.set("k3", "v3")
    
    res = cache.get_many(["k1", "k2", "k3", "missing"])
    assert res == {"k1": "v1", "k2": "v2", "k3": "v3"}
    # Verify L2 hits promoted to L1
    assert cache.l1.get("k1") == "v1"
    assert cache.l1.get("k2") == "v2"
    assert cache.l1_hits >= 1
    assert cache.l2_hits >= 2
    assert cache.misses >= 1
