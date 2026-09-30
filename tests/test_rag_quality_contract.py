from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
import tracemalloc
from contextlib import closing

import numpy as np
import pytest

from local_ai_hub.embeddings import EmbeddingModel
from local_ai_hub.rag import RAGStore


class _QueryServices:
    def __init__(self, dimension: int):
        self.dimension = dimension

    def embed(self, texts, _tenant, *, query=False, **_kwargs):
        vector = np.zeros(self.dimension, dtype=np.float32)
        vector[0] = 1.0
        return {
            "success": True,
            "embedding_space_id": "quality-space",
            "embeddings": [vector.tolist() for _ in texts],
        }


def _store(tmp_path, dimension: int = 2) -> RAGStore:
    return RAGStore(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "models": {},
            "cpu_retrieval": {},
            "workspace_cache": {},
            "rag": {
                "extensions": [".py"], "ignore_dirs": [], "chunk_chars": 4096,
                "chunk_overlap_chars": 0, "rerank_candidates": 8,
            },
            "features": {"reranker": False},
        },
        _QueryServices(dimension),
        None,
    )


def _insert_vectors(store: RAGStore, tenant: str, workspace: str, vectors: np.ndarray) -> None:
    scope_key = store._scope_key(tenant)
    with closing(store._connect()) as con:
        con.executemany(
            "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding,embedding_space) "
            "VALUES(?,?,?,?,?,?,?,?)",
            [
                (
                    scope_key, workspace, f"src/{i // 32:04d}.py", i % 32,
                    f"hash-{i}", f"fixture row {i}", sqlite3.Binary(vector.tobytes()), "quality-space",
                )
                for i, vector in enumerate(vectors)
            ],
        )
        con.commit()


def test_vector_search_streams_rows_and_keeps_golden_relevance(tmp_path, monkeypatch):
    store = _store(tmp_path)
    tenant, workspace = "tenant", "golden-workspace"
    vectors = np.asarray([[0.0, 1.0], [0.7, 0.714], [1.0, 0.0], [0.9, 0.436]], dtype=np.float32)
    _insert_vectors(store, tenant, workspace, vectors)

    class _Cursor:
        def __init__(self, cursor):
            self._cursor = cursor

        def fetchall(self):
            raise AssertionError("vector retrieval must stream rows, not fetchall")

        def fetchmany(self, size):
            return self._cursor.fetchmany(size)

        def __getattr__(self, name):
            return getattr(self._cursor, name)

    class _Connection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, *args):
            cursor = self._connection.execute(sql, *args)
            if "SELECT path, chunk_no, embedding, content_hash FROM chunks" in sql:
                return _Cursor(cursor)
            return cursor

        def close(self):
            self._connection.close()

        def commit(self):
            self._connection.commit()

    connect = store._connect
    monkeypatch.setattr(store, "_connect", lambda: _Connection(connect()))
    result = store._search_uncached("golden target", tenant, workspace, top_k=3, use_reranker=False)

    assert result["success"] is True
    assert [row["chunk_no"] for row in result["results"][:3]] == [2, 3, 1]


def test_vector_search_keeps_deterministic_ties_at_candidate_cutoff(tmp_path):
    store = _store(tmp_path)
    vectors = np.asarray([[1.0, 0.0]] * 32, dtype=np.float32)
    _insert_vectors(store, "tenant", "tie-workspace", vectors)

    result = store._search_uncached(
        "tie query", "tenant", "tie-workspace", top_k=16, use_reranker=False
    )

    assert result["success"] is True
    assert [row["chunk_no"] for row in result["results"]] == list(range(16))


def test_golden_corpus_keeps_relevant_credentials_above_realistic_distractors(tmp_path):
    store = _store(tmp_path, dimension=3)
    tenant, workspace = "tenant", "credential-golden-corpus"
    relevant = [
        (
            "runbooks/credential-rotation.md",
            "Credential rotation runbook: rotate service credentials every 30 days.",
            [1.0, 0.0, 0.0],
        ),
        (
            "security/api-key-rollover.md",
            "API key rollover procedure deploys replacement credentials before revoking old keys.",
            [0.99, 0.12, 0.0],
        ),
        (
            "operations/token-expiry.md",
            "Rotate authentication tokens before expiry and verify each service account.",
            [0.97, 0.22, 0.0],
        ),
        (
            "database/secret-renewal.md",
            "Database secret renewal schedule includes rotation, validation, and rollback.",
            [0.95, 0.31, 0.0],
        ),
        (
            "audit/credential-review.md",
            "Credential rotation audit records owner, interval, and successful rollout.",
            [0.92, 0.39, 0.0],
        ),
        (
            "identity/service-token-guide.md",
            "Service token guide explains staged credential replacement and rotation.",
            [0.89, 0.46, 0.0],
        ),
    ]
    corpus = list(relevant)
    corpus.extend(
        (
            f"reference/topic-{index:02d}.md",
            f"Reference notes for unrelated topic {index}: geography, cooking, music, and weather.",
            [0.02, 1.0, 0.0],
        )
        for index in range(58)
    )
    _insert_vectors(store, tenant, workspace, np.asarray([row[2] for row in corpus], dtype=np.float32))

    with closing(store._connect()) as con:
        for index, (path, content, _vector) in enumerate(corpus):
            con.execute(
                "UPDATE chunks SET path=?,chunk_no=0,content_hash=?,text=? "
                "WHERE tenant=? AND workspace=? AND content_hash=?",
                (path, f"golden-{index}", content, store._scope_key(tenant), workspace, f"hash-{index}"),
            )
        con.commit()

    store.config["rag"]["rerank_candidates"] = 16
    result = store._search_uncached("weekly credential rotation", tenant, workspace, top_k=10, use_reranker=False)

    assert result["success"] is True
    result_paths = [row["path"] for row in result["results"]]
    assert len(result_paths) == 10
    assert result_paths[0] == relevant[0][0]
    relevant_paths = {row[0] for row in relevant}
    relevance = [int(path in relevant_paths) for path in result_paths]
    recall_at_10 = sum(relevance) / len(relevant_paths)
    dcg_at_10 = sum(score / math.log2(rank + 2) for rank, score in enumerate(relevance))
    ideal_dcg_at_10 = sum(1.0 / math.log2(rank + 2) for rank in range(len(relevant_paths)))
    ndcg_at_10 = dcg_at_10 / ideal_dcg_at_10
    assert recall_at_10 == 1.0
    assert ndcg_at_10 >= 0.98


def test_python_cosine_fallback_rejects_non_finite_vectors():
    assert RAGStore._cosine([float("nan"), 1.0], [1.0, 0.0]) == 0.0
    assert RAGStore._cosine([float("inf"), 1.0], [1.0, 0.0]) == 0.0


def test_document_ingest_does_not_report_zero_vector_as_embedded(tmp_path):
    store = _store(tmp_path)

    class _ZeroVectorServices:
        def embed(self, texts, _tenant, **_kwargs):
            return {"success": True, "embeddings": [[0.0, 0.0] for _ in texts]}

    store.services = _ZeroVectorServices()
    result = store.ingest_document("zero-vector-workspace", "A searchable document.", title="Zero vector")

    assert result["success"] is True
    assert result["embedded"] is False


def test_subthreshold_query_uses_degraded_lexical_fallback_instead_of_vector_ties(tmp_path):
    store = _store(tmp_path)
    tenant, workspace = "tenant", "zero-query-workspace"
    _insert_vectors(store, tenant, workspace, np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32))

    class _ZeroQueryServices:
        def embed(self, texts, _tenant, *, query=False, **_kwargs):
            vectors = [[1e-10, 0.0] for _ in texts] if query else [[1.0, 0.0] for _ in texts]
            return {"success": True, "embeddings": vectors}

    store.services = _ZeroQueryServices()
    result = store._search_uncached("no lexical match", tenant, workspace, top_k=2, use_reranker=False)

    assert result["success"] is True
    assert result["degraded"] is True
    assert result["fallback"] == "bm25_fts"
    assert result["reason"] == "invalid_query_embedding"
    assert result["results"] == []


def test_fallback_embedding_reports_identity_of_backend_that_produced_vectors():
    class _Cache:
        def __init__(self):
            self.values = {}

        def get(self, key):
            return self.values.get(key)

        def set(self, key, value):
            self.values[key] = value

    model = EmbeddingModel.__new__(EmbeddingModel)
    model.config = {
        "models": {
            "embedding": "primary-model",
            "embedding_dimension": 2,
            "embedding_revision": "test-revision",
        },
        "cache": {"embeddings": True},
    }
    model.model_name = "primary-model"
    model.backend = "auto"
    model.device = "cpu"
    model.active_backend = None
    model.active_device = "cpu"
    model._active_cache_identity = "ollama:primary-model"
    model._active_embedding_dimension = 2
    model._ollama_model_name = "primary-model"
    model._loaded_model_name = "fallback-model"
    model._loaded_model_revision = "test-revision"
    model._encoder_lock = threading.RLock()
    model._identity_dimension_lock = threading.Lock()
    model._dimensions_by_identity = {}
    model._model_provenance_lock = threading.Lock()
    model._model_provenance_by_identity = {}
    model.cache = _Cache()
    model.cache_enabled = True
    model.batch_size = 32
    model._memory_hits = 0
    model._computed = 0
    model._batch_deduplicated = 0
    model._load_error = None
    model._execution_local = threading.local()
    model._encode_ollama = lambda _texts: None
    model._candidate_specs = lambda: [("sentence-transformers", "cpu")]

    def _encode_fallback(texts, **_kwargs):
        return [[1.0, 0.0] for _ in texts], "sentence-transformers"

    model._encode_st_batch = _encode_fallback
    result = model._encode_uncached(["fallback text"])

    fallback_identity = "sentence-transformers:cpu:fallback-model"
    assert result["backend"] == "sentence-transformers"
    assert result["embedding_space_id"] == model.embedding_space_id(fallback_identity)
    vector_entries = [
        entry
        for entry in model.cache.values.values()
        if isinstance(entry, dict) and "vector" in entry
    ]
    assert len(vector_entries) == 1
    assert vector_entries[0]["identity"] == fallback_identity


def test_subthreshold_query_embedding_returns_degraded_empty_results(tmp_path):
    store = _store(tmp_path)
    tenant, workspace = "tenant", "zero-query-workspace"
    _insert_vectors(
        store,
        tenant,
        workspace,
        np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
    )

    class _ZeroQueryServices(_QueryServices):
        def embed(self, texts, _tenant, *, query=False, **kwargs):
            if query:
                return {"success": True, "embeddings": [[1e-10, 0.0] for _ in texts]}
            return super().embed(texts, _tenant, query=query, **kwargs)

    store.services = _ZeroQueryServices(2)
    result = store._search_uncached("zero query", tenant, workspace, top_k=2, use_reranker=False)

    assert result["success"] is True
    assert result["results"] == []
    assert result["degraded"] is True
    assert result["fallback"] == "bm25_fts"
    assert result["reason"] == "invalid_query_embedding"


def test_numpy_vector_parse_skips_integer_overflow(tmp_path):
    store = _store(tmp_path)
    tenant, workspace = "tenant", "overflow-workspace"
    scope_key = store._scope_key(tenant)
    with closing(store._connect()) as con:
        con.execute(
            "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding,embedding_space) VALUES(?,?,?,?,?,?,?,?)",
            (scope_key, workspace, "src/overflow.py", 0, "overflow", "oversized vector", json.dumps([10 ** 1000, 0]), "quality-space"),
        )
        con.commit()

    result = store._search_uncached("overflow query", tenant, workspace, top_k=1, use_reranker=False)
    assert result["success"] is True
    assert result["results"]
    assert np.isfinite(result["results"][0]["embedding_score"])


def test_equal_scores_use_semantic_path_order_not_row_order(tmp_path):
    store = _store(tmp_path)
    tenant, workspace = "tenant", "tie-workspace"
    scope_key = store._scope_key(tenant)
    with closing(store._connect()) as con:
        con.executemany(
            "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding,embedding_space) VALUES(?,?,?,?,?,?,?,?)",
            [
                (scope_key, workspace, path, 0, f"hash-{path}", "same content", sqlite3.Binary(np.asarray([1.0, 0.0], dtype=np.float32).tobytes()), "quality-space")
                for path in ("z-last.py", "m-middle.py", "a-first.py")
            ],
        )
        con.commit()

    result = store._search_uncached("no-match-query", tenant, workspace, top_k=3, use_reranker=False)
    assert [row["path"] for row in result["results"]] == ["a-first.py", "m-middle.py", "z-last.py"]


def test_configured_candidate_count_has_hard_upper_bound(tmp_path):
    store = _store(tmp_path)
    store.config["rag"]["rerank_candidates"] = 100_000
    tenant, workspace = "tenant", "bounded-workspace"
    vectors = np.zeros((600, 2), dtype=np.float32)
    vectors[:, 0] = 1.0
    _insert_vectors(store, tenant, workspace, vectors)

    result = store._search_uncached("no-match-query", tenant, workspace, top_k=600, use_reranker=False)
    assert len(result["results"]) <= 512


@pytest.mark.parametrize(
    ("dimension", "configured_batch_size", "expected_batch_size"),
    [(2, None, 512), (2, 8192, 8192), (384, 8192, 2730)],
)
def test_search_uses_larger_bounded_vector_batches_when_configured(
    tmp_path, monkeypatch, dimension, configured_batch_size, expected_batch_size
):
    store = _store(tmp_path, dimension)
    tenant, workspace = "tenant", "larger-batch-workspace"
    vector = np.zeros(dimension, dtype=np.float32)
    vector[0] = 1.0
    _insert_vectors(store, tenant, workspace, vector.reshape(1, -1))
    if configured_batch_size is not None:
        store.config["rag"]["search_batch_size"] = configured_batch_size
    fetch_sizes = []
    connect = store._connect

    class _Cursor:
        def __init__(self, cursor):
            self._cursor = cursor

        def fetchmany(self, size):
            fetch_sizes.append(size)
            return self._cursor.fetchmany(size)

        def close(self):
            self._cursor.close()

        def __getattr__(self, name):
            return getattr(self._cursor, name)

    class _Connection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, *args):
            cursor = self._connection.execute(sql, *args)
            if "SELECT path, chunk_no, embedding, content_hash FROM chunks" in sql:
                return _Cursor(cursor)
            return cursor

        def close(self):
            self._connection.close()

        def commit(self):
            self._connection.commit()

    monkeypatch.setattr(store, "_connect", lambda: _Connection(connect()))

    result = store._search_uncached("larger batch", tenant, workspace, top_k=1, use_reranker=False)

    assert result["success"] is True
    assert fetch_sizes and max(fetch_sizes) == expected_batch_size


def test_vector_cursor_closes_before_scoring_and_after_search(tmp_path, monkeypatch):
    import local_ai_hub.rag as rag_module

    store = _store(tmp_path)
    _insert_vectors(store, "tenant", "cursor-workspace", np.asarray([[1.0, 0.0]], dtype=np.float32))
    state = {"cursor": None, "cursor_open_during_dot": False, "fetches": 0}
    real_dot = np.dot

    class _Cursor:
        def __init__(self, cursor):
            self._cursor = cursor
            self.closed = False
            state["cursor"] = self

        def fetchmany(self, size):
            state["fetches"] += 1
            return self._cursor.fetchmany(size)

        def close(self):
            self.closed = True
            self._cursor.close()

        def __getattr__(self, name):
            return getattr(self._cursor, name)

    class _Connection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, *args):
            cursor = self._connection.execute(sql, *args)
            if "SELECT path, chunk_no, embedding, content_hash FROM chunks" in sql:
                return _Cursor(cursor)
            return cursor

        def close(self):
            self._connection.close()

        def commit(self):
            self._connection.commit()

    connect = store._connect
    monkeypatch.setattr(store, "_connect", lambda: _Connection(connect()))

    def checked_dot(*args, **kwargs):
        state["cursor_open_during_dot"] = bool(state["cursor"] and not state["cursor"].closed)
        return real_dot(*args, **kwargs)

    monkeypatch.setattr(np, "dot", checked_dot)
    result = store._search_uncached("cursor query", "tenant", "cursor-workspace", top_k=1, use_reranker=False)
    assert result["success"] is True
    assert state["cursor_open_during_dot"] is False
    assert state["fetches"] >= 2
    assert state["cursor"].closed is True


def test_retrieval_latency_and_peak_memory_baseline(tmp_path, capsys):
    if os.environ.get("RAG_BENCHMARK") != "1":
        import pytest
        pytest.skip("set RAG_BENCHMARK=1 to run 100k chunk retrieval measurements")

    dimension = 384
    tenant, workspace = "benchmark-tenant", "benchmark-workspace"
    metrics = []
    batch_sizes = (512, 2048, 4096, 8192)
    for count in (1024, 16384, 100_000):
        rng = np.random.default_rng(41)
        vectors = rng.standard_normal((count, dimension), dtype=np.float32)
        vectors[0] = 0.0
        vectors[0, 0] = 1.0
        store = _store(tmp_path / str(count), dimension)
        _insert_vectors(store, tenant, workspace, vectors)

        for batch_size in batch_sizes:
            store.config["rag"]["search_batch_size"] = batch_size
            samples_ms = []
            peak_bytes = 0
            sample_count = 20 if count == 100_000 else 5
            for _ in range(2):
                warmup = store._search_uncached("benchmark query", tenant, workspace, top_k=8, use_reranker=False)
                assert warmup["success"] is True
                assert warmup["results"][0]["chunk_no"] == 0
            for _ in range(sample_count):
                started = time.perf_counter()
                result = store._search_uncached("benchmark query", tenant, workspace, top_k=8, use_reranker=False)
                samples_ms.append((time.perf_counter() - started) * 1000.0)
                assert result["success"] is True
                assert result["results"][0]["chunk_no"] == 0
            tracemalloc.start()
            memory_result = store._search_uncached("benchmark query", tenant, workspace, top_k=8, use_reranker=False)
            _, peak_bytes = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            assert memory_result["success"] is True
            assert memory_result["results"][0]["chunk_no"] == 0
            median_ms = float(np.median(samples_ms))
            p95_index = min(len(samples_ms) - 1, math.ceil(0.95 * len(samples_ms)) - 1)
            p95_ms = sorted(samples_ms)[p95_index]
            metrics.append({
                "chunks": count,
                "search_batch_size": batch_size,
                "median_ms": round(median_ms, 3),
                "p95_ms": round(float(p95_ms), 3),
                "chunks_per_second": round(count * 1000.0 / max(median_ms, 1e-9), 2),
                "peak_traced_mib": round(peak_bytes / (1024 * 1024), 3),
                "vector_batch_buffer_mib": round(batch_size * dimension * 4 / (1024 * 1024), 3),
                "warmup_samples": 2,
                "measured_samples": sample_count,
            })

    print("RAG_BENCHMARK=" + json.dumps(metrics, sort_keys=True))
    assert len(metrics) == 12
    assert all(float(row["peak_traced_mib"]) <= 16.0 for row in metrics)
    warm_100k = [row for row in metrics if row["chunks"] == 100_000]
    for row in warm_100k:
        assert float(row["p95_ms"]) <= 750.0, (
            f"100k retrieval p95 exceeded 750 ms for batch {row['search_batch_size']}: "
            f"{row['p95_ms']:.3f} ms"
        )
    peak_by_size_and_batch = {
        (int(row["chunks"]), int(row["search_batch_size"])): float(row["peak_traced_mib"])
        for row in metrics
    }
    for batch_size in batch_sizes:
        small_peak = peak_by_size_and_batch[(16_384, batch_size)]
        large_peak = peak_by_size_and_batch[(100_000, batch_size)]
        assert large_peak <= small_peak + 1.5, (
            f"peak traced memory scaled from 16k to 100k chunks for batch {batch_size}: "
            f"{small_peak:.3f} MiB -> {large_peak:.3f} MiB"
        )
