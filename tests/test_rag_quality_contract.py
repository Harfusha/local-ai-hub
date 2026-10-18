from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import threading
import time
import tracemalloc
from contextlib import closing
from pathlib import Path

import numpy as np
import pytest

from local_ai_hub.embeddings import EmbeddingModel
from local_ai_hub.rag import RAGStore


class _QueryServices:
    def __init__(self, dimension: int):
        self.dimension = dimension

    def embed(self, texts, *, query=False, **_kwargs):
        vector = np.zeros(self.dimension, dtype=np.float32)
        vector[0] = 1.0
        return {"success": True, "embedding_space_id": "quality-space", "embeddings": [vector.tolist() for _ in texts]}


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


def _insert_vectors(store: RAGStore, workspace: str, vectors: np.ndarray) -> None:
    with closing(store._connect()) as con:
        con.executemany(
            "INSERT INTO chunks(workspace,path,chunk_no,content_hash,text,embedding,embedding_space) "
            "VALUES(?,?,?,?,?,?,?)",
            [
                (
                    workspace, f"src/{i // 32:04d}.py", i % 32,
                    f"hash-{i}", f"fixture row {i}", sqlite3.Binary(vector.tobytes()), "quality-space",
                )
                for i, vector in enumerate(vectors)
            ],
        )
        con.commit()


def test_vector_search_streams_rows_and_keeps_golden_relevance(tmp_path, monkeypatch):
    store = _store(tmp_path)
    workspace = "golden-workspace"
    vectors = np.asarray([[0.0, 1.0], [0.7, 0.714], [1.0, 0.0], [0.9, 0.436]], dtype=np.float32)
    _insert_vectors(store, workspace,  vectors)

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
            if "SELECT chunks.path, chunks.chunk_no, chunks.embedding, chunks.content_hash FROM chunks AS chunks" in sql:
                return _Cursor(cursor)
            return cursor

        def close(self):
            self._connection.close()

        def commit(self):
            self._connection.commit()

    connect = store._connect
    monkeypatch.setattr(store, "_connect", lambda: _Connection(connect()))
    result = store._search_uncached("golden target", workspace,  top_k=3, use_reranker=False)

    assert result["success"] is True
    assert [row["chunk_no"] for row in result["results"][:3]] == [2, 3, 1]


def test_vector_search_skips_redundant_local_sort_for_unique_scores(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.config["rag"]["search_batch_size"] = 32
    workspace = "unique-score-workspace"
    vectors = np.asarray([[1.0, float(i + 1)] for i in range(96)], dtype=np.float32)
    _insert_vectors(store, workspace,  vectors)

    def unexpected_lexsort(*_args, **_kwargs):
        raise AssertionError("unique-score batch should not need local candidate ordering")

    monkeypatch.setattr(np, "lexsort", unexpected_lexsort)
    result = store._search_uncached("unique score query", workspace,  top_k=4, use_reranker=False)

    assert result["success"] is True
    assert [row["chunk_no"] for row in result["results"]] == [0, 1, 2, 3]


def test_vector_search_reuses_norm_buffer_for_scores(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.config["rag"]["search_batch_size"] = 32
    workspace = "score-buffer-workspace"
    vectors = np.asarray([[1.0, 0.0]] * 31 + [[0.0, 0.0]], dtype=np.float32)
    _insert_vectors(store, workspace,  vectors)

    zeros = np.zeros

    def reject_batch_score_buffer(shape, *args, **kwargs):
        if shape == 32:
            raise AssertionError("vector scoring should reuse an existing batch array")
        return zeros(shape, *args, **kwargs)

    monkeypatch.setattr(np, "zeros", reject_batch_score_buffer)
    result = store._search_uncached("score buffer query", workspace,  top_k=4, use_reranker=False)

    assert result["success"] is True
    assert [row["chunk_no"] for row in result["results"]] == [0, 1, 2, 3]
    assert all(np.isfinite(row["embedding_score"]) for row in result["results"])


def test_vector_search_keeps_deterministic_ties_at_candidate_cutoff(tmp_path):
    store = _store(tmp_path)
    vectors = np.asarray([[1.0, 0.0]] * 32, dtype=np.float32)
    _insert_vectors(store, "tie-workspace", vectors)

    result = store._search_uncached(
        "tie query", workspace="tie-workspace", top_k=16, use_reranker=False
    )

    assert result["success"] is True
    assert [row["chunk_no"] for row in result["results"]] == list(range(16))


def test_golden_corpus_keeps_relevant_credentials_above_realistic_distractors(tmp_path):
    store = _store(tmp_path, dimension=3)
    baseline_workspace = "credential-golden-baseline"
    candidate_workspace = "credential-golden-candidate"
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
    dataset_revision = hashlib.sha256(
        json.dumps(corpus, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    vectors = np.asarray([row[2] for row in corpus], dtype=np.float32)
    revision_hashes = {f"{dataset_revision}:{index}" for index in range(len(corpus))}
    for workspace in (baseline_workspace, candidate_workspace):
        _insert_vectors(store, workspace,  vectors)
        with closing(store._connect()) as con:
            for index, (path, content, _vector) in enumerate(corpus):
                con.execute(
                    "UPDATE chunks SET path=?,chunk_no=0,content_hash=?,text=? "
                    "WHERE workspace=? AND content_hash=?",
                    (
                        path,
                        f"{dataset_revision}:{index}",
                        content,
                        workspace,
                        f"hash-{index}",
                    ),
                )
            con.commit()

    with closing(store._connect()) as con:
        for workspace in (baseline_workspace, candidate_workspace):
            rows = con.execute(
                "SELECT content_hash,embedding_space FROM chunks WHERE workspace=?",
                (workspace,),
            ).fetchall()
            assert {str(row[0]) for row in rows} == revision_hashes
            assert {str(row[1]) for row in rows} == {"quality-space"}

    store.config["rag"]["rerank_candidates"] = 16
    relevant_paths = {row[0] for row in relevant}

    def paired_metrics(workspace: str) -> tuple[list[str], float, float]:
        result = store._search_uncached(
            "weekly credential rotation", workspace,  top_k=10, use_reranker=False
        )
        assert result["success"] is True
        result_paths = [row["path"] for row in result["results"]]
        assert len(result_paths) == 10
        relevance = [int(path in relevant_paths) for path in result_paths]
        recall_at_10 = sum(relevance) / len(relevant_paths)
        dcg_at_10 = sum(score / math.log2(rank + 2) for rank, score in enumerate(relevance))
        ideal_dcg_at_10 = sum(
            1.0 / math.log2(rank + 2) for rank in range(len(relevant_paths))
        )
        return result_paths, recall_at_10, dcg_at_10 / ideal_dcg_at_10

    baseline = paired_metrics(baseline_workspace)
    candidate = paired_metrics(candidate_workspace)

    assert baseline[0] == candidate[0]
    assert baseline[0][0] == relevant[0][0]
    assert candidate[1:] == baseline[1:]
    assert baseline[1] == candidate[1] == 1.0
    assert baseline[2] == candidate[2] == 1.0


def test_python_cosine_fallback_rejects_non_finite_vectors():
    assert RAGStore._cosine([float("nan"), 1.0], [1.0, 0.0]) == 0.0
    assert RAGStore._cosine([float("inf"), 1.0], [1.0, 0.0]) == 0.0


def test_document_ingest_does_not_report_zero_vector_as_embedded(tmp_path):
    store = _store(tmp_path)

    class _ZeroVectorServices:
        def embed(self, texts, **_kwargs):
            return {"success": True, "embeddings": [[0.0, 0.0] for _ in texts]}

    store.services = _ZeroVectorServices()
    result = store.ingest_document(root=str(tmp_path), title="Zero vector", workspace="zero-vector-workspace", content="A searchable document.")

    assert result["success"] is True
    assert result["embedded"] is False


def test_subthreshold_query_uses_degraded_lexical_fallback_instead_of_vector_ties(tmp_path):
    store = _store(tmp_path)
    workspace = "zero-query-workspace"
    _insert_vectors(store, workspace,  np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32))

    class _ZeroQueryServices:
        def embed(self, texts, *, query=False, **_kwargs):
            vectors = [[1e-10, 0.0] for _ in texts] if query else [[1.0, 0.0] for _ in texts]
            return {"success": True, "embeddings": vectors}

    store.services = _ZeroQueryServices()
    result = store._search_uncached("no lexical match", workspace,  top_k=2, use_reranker=False)

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

        def get_many(self, keys):
            return {k: self.values[k] for k in keys if k in self.values}

        def set(self, key, value):
            self.values[key] = value

        def set_many(self, values):
            self.values.update(values)

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
    workspace = "zero-query-workspace"
    _insert_vectors(
        store,
        workspace,
        np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
    )

    class _ZeroQueryServices(_QueryServices):
        def embed(self, texts, *, query=False, **kwargs):
            if query:
                return {"success": True, "embeddings": [[1e-10, 0.0] for _ in texts]}
            return super().embed(texts, query=query, **kwargs)

    store.services = _ZeroQueryServices(2)
    result = store._search_uncached("zero query", workspace,  top_k=2, use_reranker=False)

    assert result["success"] is True
    assert result["results"] == []
    assert result["degraded"] is True
    assert result["fallback"] == "bm25_fts"
    assert result["reason"] == "invalid_query_embedding"


def test_public_search_does_not_cache_empty_lexical_fallback(tmp_path):
    store = _store(tmp_path)

    class _ZeroQueryServices(_QueryServices):
        space_id = "quality-space"

        def __init__(self, dimension: int):
            super().__init__(dimension)
            self.query_calls = 0

        def embed(self, texts, *, query=False, **kwargs):
            if query:
                self.query_calls += 1
                return {
                    "success": True,
                    "embedding_space_id": self.space_id,
                    "embeddings": [[1e-10, 0.0] for _ in texts],
                }
            return super().embed(texts, query=query, **kwargs)

    services = _ZeroQueryServices(2)
    store.services = services

    first = store.search("zero query", use_reranker=False, workspace="zero-query-cache")
    second = store.search("zero query", use_reranker=False, workspace="zero-query-cache")

    assert first["success"] is True
    assert first["results"] == second["results"] == []
    assert first["degraded"] is second["degraded"] is True
    assert first["reason"] == second["reason"] == "invalid_query_embedding"
    assert first["search_cache"]["hit"] is False
    assert second["search_cache"]["hit"] is False
    assert services.query_calls == 2



def test_numpy_vector_parse_skips_integer_overflow(tmp_path):
    store = _store(tmp_path)
    workspace = "overflow-workspace"
    with closing(store._connect()) as con:
        con.execute(
            "INSERT INTO chunks(workspace,path,chunk_no,content_hash,text,embedding,embedding_space) VALUES(?,?,?,?,?,?,?)",
            (workspace, "src/overflow.py", 0, "overflow", "oversized vector", json.dumps([10 ** 1000, 0]), "quality-space"),
        )
        con.commit()

    result = store._search_uncached("overflow query", workspace,  top_k=1, use_reranker=False)
    assert result["success"] is True
    assert result["results"]
    assert np.isfinite(result["results"][0]["embedding_score"])


def test_equal_scores_use_semantic_path_order_not_row_order(tmp_path):
    store = _store(tmp_path)
    workspace = "tie-workspace"
    with closing(store._connect()) as con:
        con.executemany(
            "INSERT INTO chunks(workspace,path,chunk_no,content_hash,text,embedding,embedding_space) VALUES(?,?,?,?,?,?,?)",
            [
                (workspace, path, 0, f"hash-{path}", "same content", sqlite3.Binary(np.asarray([1.0, 0.0], dtype=np.float32).tobytes()), "quality-space")
                for path in ("z-last.py", "m-middle.py", "a-first.py")
            ],
        )
        con.commit()

    result = store._search_uncached("no-match-query", workspace,  top_k=3, use_reranker=False)
    assert [row["path"] for row in result["results"]] == ["a-first.py", "m-middle.py", "z-last.py"]


def test_configured_candidate_count_has_hard_upper_bound(tmp_path):
    store = _store(tmp_path)
    store.config["rag"]["rerank_candidates"] = 100_000
    workspace = "bounded-workspace"
    vectors = np.zeros((600, 2), dtype=np.float32)
    vectors[:, 0] = 1.0
    _insert_vectors(store, workspace,  vectors)

    result = store._search_uncached("no-match-query", workspace,  top_k=600, use_reranker=False)
    assert len(result["results"]) <= 512


@pytest.mark.parametrize(
    ("dimension", "configured_batch_size", "expected_batch_size"),
    [(2, None, 512), (2, 8192, 8192), (384, 8192, 2730)],
)
def test_search_uses_larger_bounded_vector_batches_when_configured(
    tmp_path, monkeypatch, dimension, configured_batch_size, expected_batch_size
):
    store = _store(tmp_path, dimension)
    workspace = "larger-batch-workspace"
    vector = np.zeros(dimension, dtype=np.float32)
    vector[0] = 1.0
    _insert_vectors(store, workspace,  vector.reshape(1, -1))
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
            if "SELECT chunks.path, chunks.chunk_no, chunks.embedding, chunks.content_hash FROM chunks AS chunks" in sql:
                return _Cursor(cursor)
            return cursor

        def close(self):
            self._connection.close()

        def commit(self):
            self._connection.commit()

    monkeypatch.setattr(store, "_connect", lambda: _Connection(connect()))

    result = store._search_uncached("larger batch", workspace,  top_k=1, use_reranker=False)

    assert result["success"] is True
    assert fetch_sizes and max(fetch_sizes) == expected_batch_size


def test_vector_cursor_closes_before_scoring_and_after_search(tmp_path, monkeypatch):
    import local_ai_hub.rag as rag_module

    store = _store(tmp_path)
    _insert_vectors(store, "cursor-workspace", np.asarray([[1.0, 0.0]], dtype=np.float32))
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
            if "SELECT chunks.path, chunks.chunk_no, chunks.embedding, chunks.content_hash FROM chunks AS chunks" in sql:
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
    result = store._search_uncached("cursor query", "cursor-workspace", top_k=1, use_reranker=False)
    assert result["success"] is True
    assert state["cursor_open_during_dot"] is False
    assert state["fetches"] >= 2
    assert state["cursor"].closed is True


def test_retrieval_latency_and_peak_memory_baseline(tmp_path, monkeypatch):
    if os.environ.get("RAG_BENCHMARK") != "1":
        import pytest
        pytest.skip("set RAG_BENCHMARK=1 to run bounded retrieval latency and memory measurements")

    dimension = 384
    workspace = "benchmark-workspace"
    metrics = []
    corpus_counts = (1024, 8192, 16384)
    for count in corpus_counts:
        store = _store(tmp_path / str(count), dimension)
        rng = np.random.default_rng(41)
        vectors = rng.standard_normal((count, dimension), dtype=np.float32)
        vectors[0] = 0.0
        vectors[0, 0] = 1.0
        store = _store(tmp_path / str(count), dimension)
        _insert_vectors(store, workspace,  vectors)

        configured_batch_size = max(32, int(store.config.get("rag", {}).get("search_batch_size", 512)))
        batch_sizes = (configured_batch_size,)
        for batch_size in batch_sizes:
            store.config["rag"]["search_batch_size"] = batch_size
            samples_ms = []
            peak_bytes = 0
            sample_count = 3
            for _ in range(2):
                warmup = store._search_uncached("benchmark query", workspace,  top_k=8, use_reranker=False)
                assert warmup["success"] is True
                assert warmup["results"][0]["chunk_no"] == 0
            for _ in range(sample_count):
                started = time.perf_counter()
                result = store._search_uncached("benchmark query", workspace,  top_k=8, use_reranker=False)
                samples_ms.append((time.perf_counter() - started) * 1000.0)
                assert result["success"] is True
                assert result["results"][0]["chunk_no"] == 0
            for _ in range(sample_count):
                tracemalloc.start()
                memory_result = store._search_uncached("benchmark query", workspace,  top_k=8, use_reranker=False)
                _, sample_peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                peak_bytes = max(peak_bytes, sample_peak)
                assert memory_result["success"] is True
                assert memory_result["results"][0]["chunk_no"] == 0
        configured_batch_size = max(32, int(store.config.get("rag", {}).get("search_batch_size", 512)))
        real_dot = np.dot
        scoring_batch_rows = []

        def observe_dot(matrix, query):
            if (
                getattr(matrix, "ndim", None) == 2
                and matrix.shape[1] == dimension
                and tuple(getattr(query, "shape", ())) == (dimension,)
            ):
                scoring_batch_rows.append(int(matrix.shape[0]))
            return real_dot(matrix, query)

        monkeypatch.setattr(np, "dot", observe_dot)
        probe = store._search_uncached("benchmark query", workspace,  top_k=8, use_reranker=False)
        monkeypatch.setattr(np, "dot", real_dot)
        assert probe["success"] is True
        assert probe["results"][0]["chunk_no"] == 0
        assert scoring_batch_rows
        assert sum(scoring_batch_rows) == count
        assert max(scoring_batch_rows) <= configured_batch_size

        metrics.append({
            "chunks": count,
            "search_batch_size": configured_batch_size,
            "median_ms": round(float(np.median(samples_ms)), 3),
            "peak_traced_mib": round(peak_bytes / (1024 * 1024), 3),
            "measured_samples": len(samples_ms),
            "peak_memory_samples": len(samples_ms),
            "scoring_batches": len(scoring_batch_rows),
            "max_scoring_batch_rows": max(scoring_batch_rows),
            "scored_chunks": sum(scoring_batch_rows),
        })

    assert len(metrics) == len(corpus_counts)
    assert [int(row["chunks"]) for row in metrics] == list(corpus_counts)
    for row in metrics:
        assert row["measured_samples"] == 3
        assert row["peak_memory_samples"] == 3
        assert row["scored_chunks"] == row["chunks"]
        assert row["max_scoring_batch_rows"] <= row["search_batch_size"]
        assert math.isfinite(float(row["median_ms"])) and float(row["median_ms"]) >= 0.0
        assert math.isfinite(float(row["peak_traced_mib"])) and float(row["peak_traced_mib"]) >= 0.0

    receipt = {
        "schema_version": 1,
        "benchmark": "rag_retrieval_latency_and_peak_memory",
        "corpus_counts": list(corpus_counts),
        "dimension": dimension,
        "dtype": "float32",
        "search_batch_sizes": sorted({int(row["search_batch_size"]) for row in metrics}),
        "measured_samples_per_corpus": 3,
        "peak_memory_samples_per_corpus": 3,
        "complexity_guard": "each corpus row is scored once in dot-product batches bounded by search_batch_size",
        "metrics": metrics,
    }
    receipt_path = Path(os.environ.get(
        "RAG_BENCHMARK_RECEIPT", str(tmp_path / "rag-benchmark-receipt.json")
    ))
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("RAG_BENCHMARK_RECEIPT=" + str(receipt_path))
    print("RAG_BENCHMARK=" + json.dumps(metrics, sort_keys=True))
