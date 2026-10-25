from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from local_ai_hub.cache import SQLiteCache, TieredCache
from local_ai_hub.services import LocalAIServices


class DummyRuntime:
    def request(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        inputs = payload.get("input", [])
        return {
            "success": True,
            "embeddings": [
                [float((hash(t) + j) % 100) / 100.0 for j in range(128)]
                for t in inputs
            ],
        }


class DummyScheduler:
    def submit(self, model: str, *, source: str, execute: Any, priority: int = 3, background: bool = False, wait_timeout: float | None = None) -> Any:
        return execute()


@pytest.fixture
def test_services(tmp_path: Path) -> LocalAIServices:
    db_path = tmp_path / "embedding_cache_test.sqlite3"
    l2 = SQLiteCache(db_path, namespace="test_embeddings")
    tiered_cache = TieredCache(l2, l1_entries=256)

    config = {
        "models": {
            "embedding_backend": "ollama",
            "embedding": "qwen3-embedding:0.6b",
        },
        "rag": {
            "embedding_batch_size": 32,
        },
        "cache": {
            "embeddings": True,
        },
    }

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = config
    services.embedding_cache = tiered_cache
    services.embedding_cache_enabled = True
    services.scheduler = DummyScheduler()
    services.runtime = DummyRuntime()
    return services


def test_batch_embed_64_items_uses_bounded_batch_cache(test_services: LocalAIServices):
    cache = test_services.embedding_cache
    assert isinstance(cache, TieredCache)

    # Spy on get_many and set_many
    original_get_many = cache.get_many
    original_set_many = cache.set_many
    get_many_spy = MagicMock(side_effect=original_get_many)
    set_many_spy = MagicMock(side_effect=original_set_many)
    cache.get_many = get_many_spy
    cache.set_many = set_many_spy

    texts = [f"Text item number {i} for embedding batch" for i in range(64)]

    # 1. First run: cold cache (all 64 are misses)
    res1 = test_services.embed(texts)
    assert res1["success"] is True
    assert len(res1["embeddings"]) == 64
    assert all(len(v) == 128 for v in res1["embeddings"])

    # Exactly 1 get_many call and 1 set_many call (not 64 individual get/set calls)
    assert get_many_spy.call_count == 1
    assert set_many_spy.call_count == 1
    assert len(get_many_spy.call_args[0][0]) == 64
    assert len(set_many_spy.call_args[0][0]) == 64

    # 2. Second run: warm cache (all 64 are hits in L1)
    get_many_spy.reset_mock()
    set_many_spy.reset_mock()

    res2 = test_services.embed(texts)
    assert res2["success"] is True
    assert len(res2["embeddings"]) == 64
    assert res2["embeddings"] == res1["embeddings"]

    # Exactly 1 get_many call, and 0 set_many calls
    assert get_many_spy.call_count == 1
    assert set_many_spy.call_count == 0


def test_mixed_cache_hits_and_misses_preserves_order(test_services: LocalAIServices):
    cache = test_services.embedding_cache
    backend = test_services.config["models"]["embedding_backend"]
    model = test_services.config["models"]["embedding"]

    known_vectors = {
        test_services._embedding_key(f"item_{i}", backend=backend, model=model, query=False): [float(i)] * 128
        for i in range(10)
    }
    cache.set_many(known_vectors)

    texts: list[str] = []
    for i in range(10):
        texts.append(f"item_{i}")
        texts.append(f"item_{i + 10}")

    res = test_services.embed(texts)
    assert res["success"] is True
    assert len(res["embeddings"]) == 20

    for i in range(10):
        idx_known = i * 2
        idx_new = i * 2 + 1
        assert res["embeddings"][idx_known] == [float(i)] * 128
        assert len(res["embeddings"][idx_new]) == 128
        assert res["embeddings"][idx_new] != [float(i)] * 128


def test_duplicate_inputs_in_batch(test_services: LocalAIServices):
    texts = ["apple", "banana", "apple", "cherry", "banana", "apple", "date"]

    res = test_services.embed(texts)
    assert res["success"] is True
    assert len(res["embeddings"]) == 7

    assert res["embeddings"][0] == res["embeddings"][2] == res["embeddings"][5]
    assert res["embeddings"][1] == res["embeddings"][4]
    assert res["embeddings"][0] != res["embeddings"][1]
    assert res["embeddings"][3] != res["embeddings"][6]


def test_query_flag_and_model_separation(test_services: LocalAIServices):
    text = "Machine learning representations"
    backend = test_services.config["models"]["embedding_backend"]
    model = test_services.config["models"]["embedding"]

    key_doc = test_services._embedding_key(text, backend=backend, model=model, query=False)
    key_query = test_services._embedding_key(text, backend=backend, model=model, query=True)
    key_other_model = test_services._embedding_key(text, backend=backend, model="other-embed-model", query=False)

    assert key_doc != key_query, "Document and query keys must not collide"
    assert key_doc != key_other_model, "Different models must not collide"


def test_corrupted_l2_entry_self_heals_as_miss(test_services: LocalAIServices, tmp_path: Path):
    cache = test_services.embedding_cache
    backend = test_services.config["models"]["embedding_backend"]
    model = test_services.config["models"]["embedding"]

    text = "Corrupt entry test text"
    key = test_services._embedding_key(text, backend=backend, model=model, query=False)

    with cache.l2._lock, closing(cache.l2._connect()) as con:
        con.execute(
            "INSERT INTO cache_entries(namespace, cache_key, value_json, created_at, accessed_at, hits) VALUES(?,?,?,?,?,0)",
            (cache.l2.namespace, key, "MALFORMED_NON_JSON_DATA", 1234567.0, 1234567.0),
        )
        con.commit()

    res = test_services.embed([text])
    assert res["success"] is True
    assert len(res["embeddings"]) == 1
    assert len(res["embeddings"][0]) == 128
