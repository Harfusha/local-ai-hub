from __future__ import annotations

import sqlite3

from local_ai_hub.rag import RAGStore, _fragment_hash


class _Services:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts, _tenant, **_kwargs):
        batch = list(texts)
        self.calls.append(batch)
        return {"success": True, "embeddings": [[float(len(text)), 1.0] for text in batch]}


class _Reranker:
    def rerank(self, query, texts, top_k=8, priority=3):
        results = [{"index": idx, "score": 1.0 / (idx + 1)} for idx in range(len(texts))]
        return {"success": True, "results": results[:top_k]}


def _store(tmp_path) -> RAGStore:
    return RAGStore(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "models": {},
            "cpu_retrieval": {},
            "workspace_cache": {},
            "rag": {"extensions": [".py"], "ignore_dirs": [], "chunk_chars": 4096, "chunk_overlap_chars": 0},
            "resilience": {"singleflight_wait_timeout_seconds": 2},
            "features": {"reranker": True},
        },
        _Services(),
        _Reranker(),
    )


def test_hybrid_rag_search_combines_fts_and_vector(tmp_path):
    store = _store(tmp_path)
    root = tmp_path / "project"
    root.mkdir()
    (root / "auth.py").write_text("def authenticate_jwt_token(token):\n    # specific keyword\n    return token.valid()\n", encoding="utf-8")
    (root / "misc.py").write_text("def unrelated_helper_function():\n    return 42\n", encoding="utf-8")

    # Index files
    res = store.index_step(str(root), "test_tenant", max_files=10)
    assert res["success"] is True

    # Search with exact keyword
    search_res = store.search("authenticate_jwt_token", "test_tenant", store.workspace_id(str(root)), top_k=5)
    assert search_res["success"] is True
    assert len(search_res["results"]) > 0
    top = search_res["results"][0]
    assert "auth.py" in top["path"]
    assert search_res.get("hybrid") is True


def test_search_marks_heuristic_rerank_as_degraded_not_model_reranked(tmp_path):
    store = _store(tmp_path)
    root = tmp_path / "project"
    root.mkdir()
    (root / "auth.py").write_text("def authenticate_token(token):\n    return token\n", encoding="utf-8")
    assert store.index_step(str(root), "tenant", max_files=10)["success"] is True

    class _FailedReranker:
        def rerank(self, *_args, **_kwargs):
            return {"success": False, "results": []}

    store.reranker = _FailedReranker()
    result = store.search("authenticate token", "tenant", store.workspace_id(str(root)), use_reranker=True)

    assert result["reranked"] is False
    assert result["degraded"] is True
    assert result["fallback"] == "heuristic_rerank"


def test_search_propagates_embedding_backend_fallback_status(tmp_path):
    store = _store(tmp_path)
    root = tmp_path / "project"
    root.mkdir()
    (root / "auth.py").write_text("def authenticate_token(token):\n    return token\n", encoding="utf-8")
    assert store.index_step(str(root), "tenant", max_files=10)["success"] is True

    original_embed = store.services.embed

    def _fallback_embed(texts, tenant, **kwargs):
        result = original_embed(texts, tenant, **kwargs)
        result.update({"degraded": True, "fallback": "sentence-transformers"})
        return result

    store.services.embed = _fallback_embed
    result = store.search("authenticate_token", "tenant", store.workspace_id(str(root)), use_reranker=False)

    assert result["degraded"] is True
    assert result["fallback"] == "sentence-transformers"


def test_rag_index_retries_transient_publish_lock(tmp_path, monkeypatch):
    store = _store(tmp_path)
    root = tmp_path / "project"
    root.mkdir()
    (root / "locked.py").write_text("def locked():\n    return 1\n", encoding="utf-8")

    state = {"failures": 1, "begins": 0}

    class _FlakyConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, *args):
            if sql == "BEGIN IMMEDIATE":
                state["begins"] += 1
                if state["failures"]:
                    state["failures"] -= 1
                    raise sqlite3.OperationalError("database is locked")
            return self._connection.execute(sql, *args)

        def close(self):
            self._connection.close()

        def __getattr__(self, name):
            return getattr(self._connection, name)

    original_connect = store._connect
    monkeypatch.setattr(store, "_connect", lambda: _FlakyConnection(original_connect()))

    result = store.index(str(root), "test_tenant", workspace="locked-workspace")

    assert result["success"] is True
    assert state["begins"] == 2
    assert len(store.services.calls) == 1
