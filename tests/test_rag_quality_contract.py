from __future__ import annotations

import json
import os
import sqlite3
import time
import tracemalloc
from contextlib import closing

import numpy as np

from local_ai_hub.rag import RAGStore


class _QueryServices:
    def __init__(self, dimension: int):
        self.dimension = dimension

    def embed(self, texts, _tenant, *, query=False, **_kwargs):
        vector = np.zeros(self.dimension, dtype=np.float32)
        vector[0] = 1.0
        return {"success": True, "embeddings": [vector.tolist() for _ in texts]}


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
            "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding) "
            "VALUES(?,?,?,?,?,?,?)",
            [
                (
                    scope_key, workspace, f"src/{i // 32:04d}.py", i % 32,
                    f"hash-{i}", f"fixture row {i}", sqlite3.Binary(vector.tobytes()),
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

    connect = store._connect
    monkeypatch.setattr(store, "_connect", lambda: _Connection(connect()))
    result = store._search_uncached("golden target", tenant, workspace, top_k=3, use_reranker=False)

    assert result["success"] is True
    assert [row["chunk_no"] for row in result["results"][:3]] == [2, 3, 1]


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


def test_numpy_vector_parse_skips_integer_overflow(tmp_path):
    store = _store(tmp_path)
    tenant, workspace = "tenant", "overflow-workspace"
    scope_key = store._scope_key(tenant)
    with closing(store._connect()) as con:
        con.execute(
            "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding) VALUES(?,?,?,?,?,?,?)",
            (scope_key, workspace, "src/overflow.py", 0, "overflow", "oversized vector", json.dumps([10 ** 1000, 0])),
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
            "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding) VALUES(?,?,?,?,?,?,?)",
            [
                (scope_key, workspace, path, 0, f"hash-{path}", "same content", sqlite3.Binary(np.asarray([1.0, 0.0], dtype=np.float32).tobytes()))
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


def test_vector_cursor_closes_before_scoring_batch(tmp_path, monkeypatch):
    import local_ai_hub.rag as rag_module

    store = _store(tmp_path)
    _insert_vectors(store, "tenant", "cursor-workspace", np.asarray([[1.0, 0.0]], dtype=np.float32))
    state = {"cursor": None, "closed_before_dot": False}
    real_dot = np.dot

    class _Cursor:
        def __init__(self, cursor):
            self._cursor = cursor
            self.closed = False
            state["cursor"] = self

        def fetchmany(self, size):
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

    connect = store._connect
    monkeypatch.setattr(store, "_connect", lambda: _Connection(connect()))

    def checked_dot(*args, **kwargs):
        state["closed_before_dot"] = bool(state["cursor"] and state["cursor"].closed)
        return real_dot(*args, **kwargs)

    monkeypatch.setattr(np, "dot", checked_dot)
    result = store._search_uncached("cursor query", "tenant", "cursor-workspace", top_k=1, use_reranker=False)
    assert result["success"] is True
    assert state["closed_before_dot"] is True


def test_retrieval_latency_and_peak_memory_baseline(tmp_path, capsys):
    if os.environ.get("RAG_BENCHMARK") != "1":
        import pytest
        pytest.skip("set RAG_BENCHMARK=1 to run bounded retrieval measurements")

    dimension = 384
    tenant, workspace = "benchmark-tenant", "benchmark-workspace"
    metrics = []
    for count in (1024, 8192, 16384):
        store = _store(tmp_path / str(count), dimension)
        rng = np.random.default_rng(41)
        vectors = rng.standard_normal((count, dimension), dtype=np.float32)
        vectors[0] = 0.0
        vectors[0, 0] = 1.0
        _insert_vectors(store, tenant, workspace, vectors)

        samples_ms = []
        peak_bytes = 0
        for _ in range(3):
            tracemalloc.start()
            started = time.perf_counter()
            result = store._search_uncached("benchmark query", tenant, workspace, top_k=8, use_reranker=False)
            samples_ms.append((time.perf_counter() - started) * 1000.0)
            _, sample_peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            peak_bytes = max(peak_bytes, sample_peak)
            assert result["success"] is True
            assert result["results"][0]["chunk_no"] == 0
        metrics.append({
            "chunks": count,
            "median_ms": round(float(np.median(samples_ms)), 3),
            "peak_traced_mib": round(peak_bytes / (1024 * 1024), 3),
        })

    print("RAG_BENCHMARK=" + json.dumps(metrics, sort_keys=True))
    assert len(metrics) == 3
