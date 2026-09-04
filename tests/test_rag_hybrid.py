from __future__ import annotations

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
