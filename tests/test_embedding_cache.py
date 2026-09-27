from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from local_ai_hub.cache import SingleFlightGroup, TieredCache, stable_hash
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
    model.enabled = True
    model._model = None
    model._load_error = None
    model.config = {
        "models": {
            "embedding": model_name,
            "embedding_backend": provider,
            "embedding_dimension": dimension,
            "embedding_revision": "test-revision",
        },
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
    model._identity_dimension_lock = threading.Lock()
    model._dimensions_by_identity = {}
    model._model_provenance_lock = threading.Lock()
    model._model_provenance_by_identity = {}
    model._loaded_model_revision = None
    model._loaded_model_digest = None
    model._encoder_lock = threading.RLock()
    model._execution_local = threading.local()
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
    model._ensure_model = lambda: True
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
        active_backend = "sentence-transformers" if provider in {"auto", "ollama"} else provider
        return encode_ollama_vectors(texts), active_backend

    def encode_ollama_vectors(texts):
        return [[float(len(text)), 1.0][:dimension] + [0.5] * max(0, dimension - 2) for text in texts]

    model._encode_ollama = encode_ollama
    if provider != "openvino":
        model._encode_st_batch = encode_st
    return model


class _RevisionedSentenceTransformer(list):
    def __init__(self, revision):
        module = type("Module", (), {})()
        module.auto_model = type("AutoModel", (), {})()
        module.auto_model.config = type("Config", (), {})()
        module.auto_model.config._commit_hash = revision
        super().__init__([module])


class _ContextGate:
    def slot(self, _priority):
        return self

    def __enter__(self):
        return None

    def __exit__(self, *_args):
        return False


class _BlockingOpenVINOEncoder:
    def __init__(self):
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()

    def encode(self, texts, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            if not self.release.wait(timeout=2):
                raise RuntimeError("timed out waiting to release OpenVINO encode")
            return [[1.0, 0.0] for _ in texts]
        raise RuntimeError("OpenVINO inference failed")


class _CPUEmbeddingEncoder:
    def encode(self, texts, **_kwargs):
        return [[0.0, 1.0] for _ in texts]


class _PartialOpenVINONPUEncoder:
    def encode(self, texts, **_kwargs):
        if texts == ["first"]:
            return [[1.0, 0.0]]
        raise RuntimeError("OpenVINO NPU rejected later item")


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


def test_persisted_dimension_restores_cache_key_after_process_restart():
    cache = _Cache()
    first = _embedding_model(cache, dimension=None)
    first_calls = []
    first._encode_ollama = lambda texts: (first_calls.append(list(texts)) or [[3.0, 4.0] for _ in texts])
    first._encode_st_batch = lambda *_args, **_kwargs: (None, "cpu")

    encoded = first.encode(["unknown configured dimension"])

    second = _embedding_model(cache, dimension=None)
    second_calls = []
    second._encode_ollama = lambda texts: (second_calls.append(list(texts)) or [[3.0, 4.0] for _ in texts])
    second._encode_st_batch = lambda *_args, **_kwargs: (None, "cpu")
    restored = second.encode(["unknown configured dimension"])

    assert encoded["success"] is True
    assert restored["success"] is True
    assert restored["cache_hits"] == 1
    assert first_calls == [["unknown configured dimension"]]
    assert second_calls == []


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
    entries = list(cache.values.values())
    vector_entries = [entry for entry in entries if isinstance(entry, dict) and "vector" in entry]
    metadata_entries = [entry for entry in entries if isinstance(entry, dict) and "vector" not in entry]
    assert len(vector_entries) == 2
    assert len(metadata_entries) == 2


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


def test_sentence_transformers_cache_key_uses_loaded_commit_revision():
    model = _embedding_model(_Cache(), provider="sentence-transformers")
    identity = model._active_cache_identity
    model._model = _RevisionedSentenceTransformer("a" * 40)
    model._record_model_provenance(identity, model=model._model)
    first = model._embedding_cache_key(identity, False, "same text")

    model._model[0].auto_model.config._commit_hash = "b" * 40
    model._record_model_provenance(identity, model=model._model)
    second = model._embedding_cache_key(identity, False, "same text")

    assert second != first


def test_sentence_transformers_bypasses_cache_when_loaded_revision_is_unknown():
    cache = _Cache()
    model = _embedding_model(cache, provider="sentence-transformers")
    model.config["models"].pop("embedding_revision")
    identity = model._active_cache_identity
    key = model._embedding_cache_key(identity, False, "same text")
    cache.set(key, {"identity": identity, "dimension": 2, "vector": [0.0, 1.0]})
    encoded = []
    model._encode_st_batch = lambda texts, **_kwargs: (encoded.extend(texts) or [[1.0, 0.0] for _ in texts], "sentence-transformers")

    result = model.encode(["same text"])

    assert result["success"] is True
    assert result["cache_hits"] == 0
    assert encoded == ["same text"]


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


def test_concurrent_openvino_fallback_keeps_each_encoder_identity():
    model = _embedding_model(_Cache(), provider="openvino")
    model.device = "NPU"
    model.active_backend = "openvino"
    model.active_device = "NPU"
    model._active_cache_identity = None
    model._loaded_model_revision = "a" * 40
    model._record_model_provenance("openvino:NPU:test-model", revision="a" * 40)
    npu_encoder = _BlockingOpenVINOEncoder()
    model._model = npu_encoder
    model._ensure_model = lambda: True

    def load_cpu_fallback(**_kwargs):
        if model._model is None:
            model._model = _CPUEmbeddingEncoder()
            model.active_backend = "sentence-transformers"
            model.active_device = "cpu"
            model._loaded_model_revision = "b" * 40
            model._record_model_provenance("sentence-transformers:cpu:test-model", revision="b" * 40)
        return True

    model._ensure_st_model = load_cpu_fallback
    model._encode_static_npu_batch = lambda encoder, texts, **_kwargs: encoder.encode(texts)
    model._cpu_gate = _ContextGate()
    second_started = threading.Event()
    original_request_key = model._encode_request_key

    def track_second_request(texts, query):
        if texts == ["second"]:
            second_started.set()
        return original_request_key(texts, query)

    model._encode_request_key = track_second_request
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(model.encode, ["first"])
        assert npu_encoder.started.wait(timeout=1)
        second = pool.submit(model.encode, ["second"])
        try:
            assert second_started.wait(timeout=1)
        finally:
            npu_encoder.release.set()
        first_result, second_result = first.result(timeout=2), second.result(timeout=2)

    assert first_result["backend"] == "openvino"
    assert first_result["device"] == "NPU"
    assert second_result["backend"] == "sentence-transformers"
    assert second_result["device"] == "cpu"
    assert first_result["embedding_space_id"] != second_result["embedding_space_id"]


def test_openvino_npu_item_fallback_recomputes_entire_batch_on_cpu():
    model = _embedding_model(_Cache(), provider="openvino")
    model.device = "NPU"
    model.active_backend = "openvino"
    model.active_device = "NPU"
    model._active_cache_identity = "openvino:NPU:test-model"
    model._model = _PartialOpenVINONPUEncoder()
    model._loaded_model_revision = "a" * 40
    model._record_model_provenance(model._active_cache_identity, revision="a" * 40)
    model._cpu_gate = _ContextGate()

    def load_cpu_fallback(**_kwargs):
        if model._model is None:
            model._model = _CPUEmbeddingEncoder()
            model.active_backend = "sentence-transformers"
            model.active_device = "cpu"
            model._record_model_provenance(
                "sentence-transformers:cpu:test-model", revision="b" * 40
            )
        return True

    model._ensure_st_model = load_cpu_fallback

    vectors, backend = model._encode_st_batch(
        ["first", "second", "third"], query=False, priority=3
    )

    assert vectors == [[0.0, 1.0], [0.0, 1.0], [0.0, 1.0]]
    assert backend == "sentence-transformers"
    assert model._execution_local.snapshot["identity"] == "sentence-transformers:cpu:test-model"


def test_concurrent_distinct_provider_dimensions_do_not_cross_contaminate_cache_identity():
    cache = _Cache()
    model = _embedding_model(cache)
    model.backend = "auto"
    model._active_cache_identity = None
    model._active_embedding_dimension = None
    first_at_store = threading.Event()
    release_first = threading.Event()
    original_key = model._embedding_cache_key

    def barrier_key(identity, query, text, **kwargs):
        key = original_key(identity, query, text, **kwargs)
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
    entries = list(cache.values.values())
    vector_entries = [entry for entry in entries if isinstance(entry, dict) and "vector" in entry]
    metadata_entries = [entry for entry in entries if isinstance(entry, dict) and "vector" not in entry]
    assert len(vector_entries) == 1
    assert len(metadata_entries) == 1
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
    model._encode_st_batch = lambda texts, **_kwargs: (
        [[float(len(text)), 1.0] for text in texts],
        "sentence-transformers",
    )

    result = model.encode(["fallback embedding"])

    assert result["success"] is True
    assert result["degraded"] is True
    assert result["fallback"] == "sentence-transformers"


def test_backend_fallback_reports_embedding_space_of_backend_that_encoded_vectors():
    cache = _Cache()
    model = _embedding_model(cache, provider="ollama")
    ollama_identity = "ollama:test-model"
    cache.set(
        model._embedding_cache_key(ollama_identity, False, "cached item"),
        {"identity": ollama_identity, "dimension": 2, "vector": [0.0, 1.0]},
    )
    model._encode_ollama = lambda _texts: None

    def encode_on_sentence_transformers(texts, **_kwargs):
        identity = "sentence-transformers:cpu:test-model"
        revision = "b" * 40
        model.active_backend = "sentence-transformers"
        model.active_device = "cpu"
        model._loaded_model_revision = revision
        model._record_model_provenance(identity, revision=revision)
        model._execution_local.snapshot = {
            "identity": identity,
            "backend": "sentence-transformers",
            "device": "cpu",
            "model": "test-model",
            "revision": revision,
            "digest": None,
        }
        return [[float(len(text)), 1.0] for text in texts], "sentence-transformers"

    model._encode_st_batch = encode_on_sentence_transformers

    result = model.encode(["cached item", "fallback identity"])

    fallback_identity = "sentence-transformers:cpu:test-model"
    assert result["embedding_space_id"] == model.embedding_space_id(fallback_identity)
    assert model._active_cache_identity == fallback_identity
    assert result["embeddings"][0] == [float(len("cached item")), 1.0]
    fallback_cached = cache.get(model._embedding_cache_key(fallback_identity, False, "cached item"))
    assert fallback_cached == {
        "identity": fallback_identity,
        "dimension": 2,
        "vector": [float(len("cached item")), 1.0],
    }


def test_openvino_cpu_fallback_is_reported_as_degraded_with_actual_space():
    model = _embedding_model(_Cache(), provider="openvino")
    model.device = "NPU"
    model.active_backend = "openvino"
    model.active_device = "NPU"
    model._active_cache_identity = None
    model._loaded_model_revision = "a" * 40
    model._ensure_model = lambda: True

    def encode_on_cpu(texts, **_kwargs):
        model.active_backend = "sentence-transformers"
        model.active_device = "cpu"
        return [[1.0, 0.0] for _ in texts], "sentence-transformers"

    model._encode_st_batch = encode_on_cpu

    result = model.encode(["fallback embedding"])

    fallback_identity = "sentence-transformers:cpu:test-model"
    assert result["success"] is True
    assert result["degraded"] is True
    assert result["fallback"] == "sentence-transformers"
    assert result["backend"] == "sentence-transformers"
    assert result["device"] == "cpu"
    assert result["embedding_space_id"] == model.embedding_space_id(fallback_identity, dimension=2)


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


def test_embedding_cache_ignores_legacy_key_without_revision_identity():
    cache = _Cache()
    model = _embedding_model(cache)
    identity = model._active_cache_identity
    legacy_key = stable_hash({"identity": identity, "query": False, "text": "same text"})
    cache.values[legacy_key] = {
        "identity": identity,
        "dimension": 2,
        "vector": [-1.0, 0.0],
    }

    result = model.encode(["same text"])

    assert result["cache_hits"] == 0
    assert model.calls == 1
    assert result["embeddings"] == [[float(len("same text")), 1.0]]


def test_embedding_space_identity_includes_resolved_dimension():
    model = _embedding_model(_Cache())
    identity = model._active_cache_identity
    model.config["models"].pop("embedding_dimension")

    two_dimensions = model.embedding_space_id(identity, dimension=2)
    three_dimensions = model.embedding_space_id(identity, dimension=3)

    assert two_dimensions != three_dimensions


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
