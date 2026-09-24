from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from local_ai_hub.cache import SingleFlightGroup, TieredCache
from local_ai_hub.embeddings import EmbeddingModel
from local_ai_hub.services import LocalAIServices


class _EmbeddingBackend:
    def __init__(self):
        self.calls = []

    def encode(self, texts, **_kwargs):
        batch = list(texts)
        self.calls.append(batch)
        return {"success": True, "embeddings": [[float(len(text)), 1.0] for text in batch]}


class _Cache:
    def __init__(self):
        self.values = {}
        self.writes = []

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value
        self.writes.append((key, value))

    def stats(self):
        return {"entries": len(self.values)}


def _embedding_model(cache, *, provider="ollama", model_name="test-model", dimension=2, delay=0):
    model = EmbeddingModel.__new__(EmbeddingModel)
    model.config = {
        "models": {"embedding": model_name, "embedding_backend": provider, "embedding_dimension": dimension},
        "cache": {"embeddings": True},
    }
    model.model_name = model_name
    model.backend = provider
    model.device = "cpu"
    model.active_backend = None
    model.active_device = "cpu"
    model._active_cache_identity = (
        f"ollama:{model_name}" if provider == "ollama" else f"{provider}:cpu:{model_name}"
    )
    model._active_embedding_dimension = dimension
    model._ollama_model_name = model_name
    model._loaded_model_name = model_name
    model.cache = cache
    model.cache_enabled = True
    model.flight_group = SingleFlightGroup(shards=16, default_timeout_seconds=3)
    model.batch_size = 32
    model._memory_hits = 0
    model._computed = 0
    model._batch_deduplicated = 0
    model._load_error = None
    model.calls = 0
    model.started = threading.Event()
    model.release = threading.Event()

    def encode_ollama(texts):
        model.calls += 1
        model.started.set()
        if delay:
            model.release.wait(timeout=3)
        return [[float(len(text)), 1.0][:dimension] + [0.5] * max(0, dimension - 2) for text in texts]

    def encode_st(texts, **_kwargs):
        model.calls += 1
        return encode_ollama_vectors(texts), provider

    def encode_ollama_vectors(texts):
        return [[float(len(text)), 1.0][:dimension] + [0.5] * max(0, dimension - 2) for text in texts]

    model._encode_ollama = encode_ollama
    model._encode_st_batch = encode_st
    return model


def test_embed_reuses_cached_vectors_and_preserves_batch_order():
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {
        "models": {"embedding_backend": "sentence-transformers", "embedding": "test-model"},
        "cache": {"embeddings": True},
    }
    service.embeddings = _EmbeddingBackend()
    service.embedding_cache = _Cache()

    first = service.embed(["alpha", "beta"], "tenant")
    second = service.embed(["beta", "alpha"], "tenant")

    assert first["embeddings"] == [[5.0, 1.0], [4.0, 1.0]]
    assert second["embeddings"] == [[4.0, 1.0], [5.0, 1.0]]
    assert service.embeddings.calls == [["alpha", "beta"]]


def test_embedding_model_cache_hit_skips_backend_and_reports_latency():
    model = _embedding_model(_Cache())

    started = time.perf_counter()
    first = model.encode(["same input"])
    first_seconds = time.perf_counter() - started
    started = time.perf_counter()
    second = model.encode(["same input"])
    repeat_seconds = time.perf_counter() - started

    assert first["embeddings"] == second["embeddings"]
    assert first["computed"] == 1
    assert second["cache_hits"] == 1
    assert model.calls == 1
    print(
        f"embedding-cache latency first={first_seconds * 1000:.3f}ms "
        f"repeat={repeat_seconds * 1000:.3f}ms backend_calls={model.calls}"
    )


@pytest.mark.parametrize(
    ("first_provider", "first_model", "first_dimension", "second_provider", "second_model", "second_dimension"),
    [
        ("ollama", "model-a", 2, "sentence-transformers", "model-a", 2),
        ("ollama", "model-a", 2, "ollama", "model-b", 2),
        ("ollama", "model-a", 2, "ollama", "model-a", 3),
    ],
)
def test_cache_identity_invalidates_provider_model_or_dimension(
    first_provider, first_model, first_dimension, second_provider, second_model, second_dimension
):
    cache = _Cache()
    first_model_instance = _embedding_model(
        cache, provider=first_provider, model_name=first_model, dimension=first_dimension
    )
    second_model_instance = _embedding_model(
        cache, provider=second_provider, model_name=second_model, dimension=second_dimension
    )

    first_model_instance.encode(["same input"])
    second = second_model_instance.encode(["same input"])

    assert second["cache_hits"] == 0
    assert second_model_instance.calls == 1
    assert len(cache.values) == 2


def test_cache_key_distinguishes_normalized_and_raw_provider_vectors():
    cache = _Cache()
    ollama = _embedding_model(cache, provider="ollama")
    sentence_transformers = _embedding_model(cache, provider="sentence-transformers")

    assert ollama._embedding_normalized(ollama._active_cache_identity) is False
    assert sentence_transformers._embedding_normalized(sentence_transformers._active_cache_identity) is True
    assert ollama._embedding_cache_key(ollama._active_cache_identity, False, "text") != (
        sentence_transformers._embedding_cache_key(
            sentence_transformers._active_cache_identity, False, "text"
        )
    )


def test_concurrent_identical_encode_calls_share_one_backend_execution():
    model = _embedding_model(_Cache(), delay=0.1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(model.encode, ["same input"])
        assert model.started.wait(timeout=1)
        second = pool.submit(model.encode, ["same input"])
        deadline = time.monotonic() + 1
        while model.flight_group.coalesced_calls == 0 and time.monotonic() < deadline:
            time.sleep(0.001)
        assert model.flight_group.coalesced_calls == 1
        model.release.set()
        first_result, second_result = first.result(timeout=2), second.result(timeout=2)

    assert first_result["embeddings"] == second_result["embeddings"]
    assert model.calls == 1
    assert model.flight_group.coalesced_calls == 1


def test_concurrent_distinct_provider_dimensions_do_not_cross_contaminate_cache_identity():
    cache = _Cache()
    model = _embedding_model(cache)
    model.backend = "auto"
    model._active_cache_identity = None
    model._active_embedding_dimension = None
    first_at_store = threading.Event()
    release_first = threading.Event()
    original_key = model._embedding_cache_key

    def barrier_key(identity, query, text):
        key = original_key(identity, query, text)
        if text == "request-a":
            first_at_store.set()
            assert release_first.wait(timeout=2)
        return key

    model._embedding_cache_key = barrier_key
    model._encode_ollama = lambda texts: [[1.0, 0.0] for _ in texts] if texts == ["request-a"] else None
    model._encode_st_batch = lambda texts, **_kwargs: ([[0.0, 1.0, 0.0] for _ in texts], "sentence-transformers")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(model.encode, ["request-a"])
        assert first_at_store.wait(timeout=1)
        second = pool.submit(model.encode, ["request-b"])
        try:
            second_result = second.result(timeout=1)
        finally:
            release_first.set()
        first_result = first.result(timeout=1)

    first_key = original_key("ollama:test-model", False, "request-a")
    first_entry = cache.values[first_key]
    assert first_result["embeddings"] == [[1.0, 0.0]]
    assert second_result["embeddings"] == [[0.0, 1.0, 0.0]]
    assert first_entry["identity"] == "ollama:test-model"
    assert first_entry["dimension"] == 2
    assert len(first_entry["vector"]) == 2


def test_cancelled_inflight_encode_is_removed_and_can_retry():
    cache = _Cache()
    model = _embedding_model(cache)
    calls = 0

    def cancel_then_encode(texts):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise KeyboardInterrupt("cancelled")
        return [[1.0, 0.0] for _ in texts]

    model._encode_ollama = cancel_then_encode
    with pytest.raises(KeyboardInterrupt, match="cancelled"):
        model.encode(["retry after cancellation"])

    result = model.encode(["retry after cancellation"])

    assert result["success"] is True
    assert calls == 2
    assert len(cache.values) == 1
    assert model.flight_group.stats()["inflight"] == 0


def test_non_finite_backend_output_is_rejected_without_caching():
    cache = _Cache()
    model = _embedding_model(cache)
    model._encode_ollama = lambda texts: [[float("nan"), 0.0] for _ in texts]
    model._encode_st_batch = lambda *_args, **_kwargs: (None, "cpu")

    result = model.encode(["invalid vector"])

    assert result["success"] is False
    assert cache.values == {}

def test_zero_norm_backend_output_is_rejected_without_caching():
    cache = _Cache()
    model = _embedding_model(cache)
    model._encode_ollama = lambda texts: [[0.0, 0.0] for _ in texts]
    model._encode_st_batch = lambda *_args, **_kwargs: (None, "cpu")

    result = model.encode(["zero vector"])

    assert result["success"] is False
    assert cache.values == {}


def test_backend_fallback_is_reported_as_degraded():
    model = _embedding_model(_Cache(), provider="ollama")
    model._encode_ollama = lambda _texts: None
    model._encode_st_batch = lambda texts, **_kwargs: ([[float(len(text)), 1.0] for text in texts], "sentence-transformers")

    result = model.encode(["fallback embedding"])

    assert result["success"] is True
    assert result["degraded"] is True
    assert result["fallback"] == "sentence-transformers"

def test_embedding_cache_key_changes_with_digest_and_revision():
    model = _embedding_model(_Cache())
    identity = model._active_cache_identity
    original = model._embedding_cache_key(identity, False, "same text")
    model.config["models"]["embedding_digest"] = "sha256:first"
    with_digest = model._embedding_cache_key(identity, False, "same text")
    model.config["models"]["embedding_revision"] = "revision-two"
    with_revision = model._embedding_cache_key(identity, False, "same text")

    assert with_digest != original
    assert with_revision != with_digest


@pytest.mark.parametrize("partial", [True, False])
def test_failed_or_partial_backend_output_never_enters_cache(partial):
    cache = _Cache()
    model = _embedding_model(cache)
    if partial:
        model._encode_ollama = lambda texts: [[1.0, 0.0]]
    else:
        model._encode_ollama = lambda texts: [[1.0, 0.0], [0.0, 1.0, 0.0]]
    model._encode_st_batch = lambda *_args, **_kwargs: (None, "cpu")

    result = model.encode(["first", "second"])

    assert result["success"] is False
    assert cache.values == {}


def test_embedding_l1_cache_evicts_at_configured_bound_and_reports_memory_entries():
    l2 = _Cache()
    cache = TieredCache(l2, l1_entries=16, l1_ttl_seconds=60)
    model = _embedding_model(cache)

    model.encode([f"unique-{index}" for index in range(128)])
    stats = cache.stats()["l1"]

    assert stats["entries"] <= stats["max_entries"]
    assert stats["evictions"] > 0
    print(f"embedding-cache L1 entries={stats['entries']}/{stats['max_entries']} evictions={stats['evictions']}")
