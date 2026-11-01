from local_ai_hub.opencode_boundary import generation_scope, path_allowed
from test_rag_hybrid import _store


def test_local_rag_search_uses_index_without_embedding_or_reranking(tmp_path):
    store = _store(tmp_path)
    root = tmp_path / "project"
    root.mkdir()
    (root / "sample.py").write_text("def rare_lexical_probe():\n    return 42\n", encoding="utf-8")
    assert store.index_step(str(root), max_files=10)["success"]
    workspace = store.workspace_id(str(root))
    store.services.embed = lambda *a, **kw: (_ for _ in ()).throw(AssertionError("embedding called"))
    store.reranker.rerank = lambda *a, **kw: (_ for _ in ()).throw(AssertionError("reranking called"))

    with generation_scope("opencode-local"):
        result = store.search("rare_lexical_probe", workspace=workspace)

    assert result["success"]
    assert result["retrieval_mode"] == "lexical_fallback"
    assert result["reason"] == "opencode_local_lexical_only"
    assert any(item["path"] == "sample.py" for item in result["results"])
    assert path_allowed("opencode-local", "POST", "/api/rag/search")
