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


def test_embedding_encode_cold_batch_uses_one_sqlite_batch_read(tmp_path: Path, monkeypatch):
    from local_ai_hub.embeddings import EmbeddingModel

    class DeterministicBackend:
        prompts = {}

    model = EmbeddingModel(
        {
            "server": {"state_dir": str(tmp_path)},
            "models": {"embedding": "test-model", "embedding_backend": "sentence-transformers"},
            "cache": {"embeddings": True},
        }
    )
    model._model = DeterministicBackend()
    model._active_cache_identity = "sentence-transformers:cpu:test-model"
    model.active_backend = "sentence-transformers"
    model.active_device = "cpu"
    model._loaded_model_name = "test-model"
    model._encode_st_batch = lambda texts, **_kwargs: (
        [[float(len(text)), 1.0] for text in texts],
        "sentence-transformers",
    )

    statements: list[str] = []
    sqlite_cache = model.cache.l2
    original_connect = sqlite_cache._connect

    def traced_connect():
        connection = original_connect()
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(sqlite_cache, "_connect", traced_connect)
    texts = ["cold alpha", "cold beta", "cold alpha"]
    cache_keys = [model._embedding_cache_key(model._active_cache_identity, False, text) for text in texts]
    cache_batches = []
    original_set_many = model.cache.set_many

    def traced_set_many(items):
        cache_batches.append(dict(items))
        original_set_many(items)

    monkeypatch.setattr(model.cache, "set_many", traced_set_many)

    result = model.encode(texts)

    assert result["success"] is True
    assert result["computed"] == 2
    assert result["batch_deduplicated"] == 1
    assert result["embeddings"][0] == result["embeddings"][2]
    assert len(cache_batches) == 1
    assert len(cache_batches[0]) == 2
    assert {entry["identity"] for entry in cache_batches[0].values()} == {model._active_cache_identity}
    batch_reads = [
        sql for sql in statements
        if "SELECT cache_key, value_json, created_at FROM cache_entries" in sql
        and "cache_key IN (" in sql
    ]
    per_key_reads = [
        sql for sql in statements
        if "SELECT value_json, created_at FROM cache_entries" in sql
        and "cache_key=" in sql
        and any(key in sql for key in cache_keys)
    ]
    assert len(batch_reads) == 1
    assert per_key_reads == []


def test_embedding_encode_rejects_cache_without_batch_write_contract(tmp_path: Path):
    from local_ai_hub.embeddings import EmbeddingModel

    class DeterministicBackend:
        prompts = {}

    model = EmbeddingModel(
        {
            "server": {"state_dir": str(tmp_path)},
            "models": {"embedding": "test-model", "embedding_backend": "sentence-transformers"},
            "cache": {"embeddings": True},
        }
    )
    model._model = DeterministicBackend()
    model._active_cache_identity = "sentence-transformers:cpu:test-model"
    model.active_backend = "sentence-transformers"
    model.active_device = "cpu"
    model._loaded_model_name = "test-model"
    model._encode_st_batch = lambda texts, **_kwargs: (
        [[float(len(text)), 1.0] for text in texts],
        "sentence-transformers",
    )
    single_writes: list[tuple[str, object]] = []

    underlying_cache = model.cache

    class SingleWriteOnlyCache:
        def get_many(self, keys):
            return underlying_cache.get_many(keys)

        def set(self, key, value):
            single_writes.append((key, value))

    model.cache = SingleWriteOnlyCache()

    result = model.encode(["contract check"])

    assert result["success"] is False
    assert "batch writes" in result["error"]
    assert single_writes == []


def test_embedding_encode_invalid_final_vector_writes_no_cache_cohort(tmp_path: Path, monkeypatch):
    from local_ai_hub.embeddings import EmbeddingModel

    class DeterministicBackend:
        prompts = {}

    model = EmbeddingModel(
        {
            "server": {"state_dir": str(tmp_path)},
            "models": {"embedding": "test-model", "embedding_backend": "sentence-transformers"},
            "cache": {"embeddings": True},
        }
    )
    model._model = DeterministicBackend()
    model._active_cache_identity = "sentence-transformers:cpu:test-model"
    model.active_backend = "sentence-transformers"
    model.active_device = "cpu"
    model._loaded_model_name = "test-model"
    model._encode_st_batch = lambda texts, **_kwargs: (
        [[float(len(text)), 1.0] for text in texts[:-1]] + [[float("nan"), 1.0]],
        "sentence-transformers",
    )
    cache_batches = []
    monkeypatch.setattr(model.cache, "set_many", lambda items: cache_batches.append(dict(items)))
    texts = ["valid alpha", "invalid omega"]
    cache_keys = [
        model._embedding_cache_key(model._active_cache_identity, False, text)
        for text in texts
    ]

    result = model.encode(texts)

    assert result["success"] is False
    assert "invalid vector" in result["error"]
    assert cache_batches == []
    assert model.cache.get_many(cache_keys) == {}


def test_tiered_get_many_invalidates_l1_after_cross_instance_clear(tmp_path: Path):
    db_path = tmp_path / "coordinated.sqlite3"
    writer = TieredCache(SQLiteCache(db_path, "command:task24"))
    reader = TieredCache(SQLiteCache(db_path, "command:task24"))
    writer.set("shared-key", {"value": "before-clear"})

    assert reader.get_many(["shared-key"]) == {"shared-key": {"value": "before-clear"}}
    assert writer.clear() == 1

    assert reader.get_many(["shared-key"]) == {}
