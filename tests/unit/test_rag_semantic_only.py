import json
from contextlib import closing

from local_ai_hub.rag import RAGStore


class _Embeddings:
    space_id = "semantic-only-test"

    def __init__(self):
        self.available = True

    def embed(self, texts, **kwargs):
        if not self.available:
            return {"success": False, "error": "offline"}
        return {"success": True, "embeddings": [[1.0, 0.0] for _ in texts],
                "embedding_space_id": self.space_id}


def _store(tmp_path):
    embeddings = _Embeddings()
    store = RAGStore({"server": {"state_dir": str(tmp_path)},
                      "models": {"embedding_dimension": 2}}, embeddings)
    root = tmp_path / "root"
    root.mkdir()
    (root / "binding.txt").write_text("", encoding="utf-8")
    assert store.index_paths_step(str(root), workspace="test", paths=["binding.txt"])["success"]
    with closing(store._connect()) as con:
        con.execute("INSERT INTO chunks(workspace,path,chunk_no,content_hash,text,embedding,embedding_space) VALUES(?,?,?,?,?,?,?)",
                    ("test", "doc.txt", 0, "hash", "example", json.dumps([1.0, 0.0]), embeddings.space_id))
        con.commit()
    return store, embeddings


def test_semantic_only_does_not_query_lexical_backend(tmp_path, monkeypatch):
    store, _ = _store(tmp_path)
    def unexpected(*args, **kwargs):
        raise AssertionError("semantic-only search consulted FTS")
    monkeypatch.setattr(store, "_search_fts_candidates", unexpected)
    result = store.search("example", workspace="test", use_reranker=False, semantic_only=True)
    assert result["success"] and result["results"]
    assert result["hybrid"] is False


def test_semantic_only_does_not_mislabel_lexical_fallback(tmp_path, monkeypatch):
    store, embeddings = _store(tmp_path)
    embeddings.available = False
    def unexpected(*args, **kwargs):
        raise AssertionError("semantic-only fallback consulted FTS")
    monkeypatch.setattr(store, "_search_fts_candidates", unexpected)
    result = store.search("example", workspace="test", use_reranker=False, semantic_only=True)
    assert result["success"] and result["results"] == []
    assert result["degraded"] and result["fallback"] == "embedding_backend"


def test_semantic_only_has_separate_cache_identity(tmp_path):
    store, _ = _store(tmp_path)
    hybrid = store.search("example", workspace="test", use_reranker=False)
    semantic = store.search("example", workspace="test", use_reranker=False, semantic_only=True)
    assert hybrid["success"] and semantic["success"]
    assert semantic["search_cache"]["hit"] is False


def test_semantic_only_recovers_after_embedding_outage(tmp_path):
    store, embeddings = _store(tmp_path)
    embeddings.available = False
    unavailable = store.search("example", workspace="test", use_reranker=False, semantic_only=True)
    embeddings.available = True
    recovered = store.search("example", workspace="test", use_reranker=False, semantic_only=True)
    assert unavailable["degraded"]
    assert recovered["success"] and recovered["results"]
