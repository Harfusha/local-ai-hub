from __future__ import annotations

from local_ai_hub.search_modes import (
    expand_semantic_query,
    fuse_search_results,
    prefers_lexical_precision,
)
from local_ai_hub.services import LocalAIServices


def _service(monkeypatch, rag_rows=None, rag_meta=None):
    service = object.__new__(LocalAIServices)
    service.config = {"features": {"rag": True}}
    rows = rag_rows or []
    meta = rag_meta or {"success": True, "index_state": "partial_or_candidate_bounded"}
    monkeypatch.setattr(service, "_repo_rag_search", lambda root, query, top_k: (rows, meta))
    return service


def test_hybrid_fusion_deduplicates_files_and_rewards_backend_agreement():
    lexical = [
        {"path": "src/setup.py", "start_line": 10, "score": 9.0, "text": "setup"},
        {"path": "src/setup.py", "start_line": 30, "score": 8.0, "text": "duplicate file"},
        {"path": "docs/install.md", "start_line": 4, "score": 7.0, "text": "install"},
    ]
    rag = [
        {"path": "docs\\install.md", "chunk_no": 2, "embedding_score": 0.91, "text": "install"},
        {"path": "src/other.py", "chunk_no": 0, "embedding_score": 0.82, "text": "other"},
    ]

    fused, metadata = fuse_search_results(lexical, rag, limit=10, offset=0)

    assert [item["path"] for item in fused] == ["docs/install.md", "src/setup.py", "src/other.py"]
    assert fused[0]["sources"] == ["lexical", "rag"]
    assert fused[1]["sources"] == ["lexical"]
    assert fused[2]["sources"] == ["rag"]
    assert metadata["candidate_count"] == 3
    assert metadata["count_exact"] is False


def test_hybrid_fusion_paging_is_stable_and_semantic_counts_are_not_lexical_counts():
    lexical = [{"path": f"src/{name}.py", "start_line": 1} for name in ("a", "b", "c")]
    rag = [{"path": f"docs/{name}.md", "chunk_no": 0} for name in ("d", "e", "f")]

    page_one, first = fuse_search_results(lexical, rag, limit=2, offset=0)
    page_two, second = fuse_search_results(lexical, rag, limit=2, offset=2)
    all_results, _ = fuse_search_results(lexical, rag, limit=20, offset=0)

    assert page_one + page_two == all_results[:4]
    assert first["candidate_count"] == second["candidate_count"] == 6
    assert first["total_matches"] is None
    assert first["count_exact"] is False


def test_hybrid_fusion_uses_stable_tie_breaking():
    lexical = [{"path": "z/file.py"}, {"path": "a/file.py"}]
    rag = [{"path": "a/file.py"}, {"path": "z/file.py"}]
    fused, _metadata = fuse_search_results(lexical, rag, limit=10, offset=0)
    assert [item["path"] for item in fused] == ["a/file.py", "z/file.py"]


def test_symbol_like_hybrid_queries_put_exact_lexical_hits_first():
    assert prefers_lexical_precision("repo_search")
    assert prefers_lexical_precision("C++")
    assert not prefers_lexical_precision("Local AI Hub installation")


def test_czech_semantic_query_gets_bounded_english_terms_without_changing_lexical_text():
    original = "Jak nastavit limit code indexu?"
    expanded, applied = expand_semantic_query(original)

    assert applied is True
    assert expanded == (
        original + " how configure size index code_index max_index_bytes "
        "database storage eviction maximum bytes"
    )
    assert expand_semantic_query("repo_search") == ("repo_search", False)
    english, english_applied = expand_semantic_query("Local AI Hub installation")
    assert english == "Local AI Hub installation install setup getting started bootstrap"
    assert english_applied is True
    assert expand_semantic_query("Jak instalace Local AI Hub?")[0].endswith(
        "how installation install setup getting started bootstrap"
    )
    assert expand_semantic_query("How to set a size limit?")[1] is False


def test_installation_expansion_targets_semantic_candidates_only(monkeypatch):
    service = _service(monkeypatch, [{"path": "docs/INSTALLATION.md", "text": "install"}])
    rag_calls = []
    lexical_calls = []
    monkeypatch.setattr(
        service, "_repo_rag_search",
        lambda root, query, top_k: (rag_calls.append(query) or
                                   [{"path": "docs/INSTALLATION.md", "text": "install"}],
                                   {"success": True, "index_state": "current"}),
    )
    monkeypatch.setattr(
        service, "_repo_search_lexical",
        lambda root, query, *args, **kwargs: (
            lexical_calls.append(query) or
            {"success": True, "results": [{"path": "docs/INSTALLATION.md", "text": "install"}],
             "count_exact": False, "total_matches": None}
        ),
    )

    result = service.repo_search(".", "Local AI Hub installation", search_mode="hybrid")

    assert rag_calls == ["Local AI Hub installation install setup getting started bootstrap"]
    assert lexical_calls == ["Local AI Hub installation install setup getting started bootstrap"]
    assert result["query_expansion_applied"] is True

    lexical_calls.clear()
    lexical = service.repo_search(".", "Local AI Hub installation", search_mode="lexical")
    assert lexical_calls == ["Local AI Hub installation"]
    assert lexical["search_mode"] == "lexical"


def test_rag_mode_applies_czech_expansion_only_to_semantic_candidates(monkeypatch):
    service = _service(monkeypatch, [{"path": "docs/index.md", "text": "index"}])
    calls = []
    monkeypatch.setattr(
        service, "_repo_rag_search",
        lambda root, query, top_k: (calls.append(query) or [{"path": "docs/index.md", "text": "index"}],
                                   {"success": True, "index_state": "available"}),
    )

    result = service.repo_search(".", "Jak nastavit limit code indexu?", search_mode="rag")

    assert calls == [
        "Jak nastavit limit code indexu? how configure size index code_index max_index_bytes "
        "database storage eviction maximum bytes"
    ]
    assert result["query_expansion_applied"] is True


def test_hybrid_uses_expanded_terms_for_bounded_candidates_but_not_exact_lexical_mode(monkeypatch):
    service = _service(monkeypatch, [{"path": "docs/CODE_INDEX.md", "text": "index budget"}])
    rag_calls = []
    lexical_calls = []
    monkeypatch.setattr(
        service, "_repo_rag_search",
        lambda root, query, top_k: (rag_calls.append(query) or
                                   [{"path": "docs/CODE_INDEX.md", "text": "index budget"}],
                                   {"success": True, "index_state": "available"}),
    )
    monkeypatch.setattr(
        service, "_repo_search_lexical",
        lambda root, query, *args, **kwargs: (
            lexical_calls.append((query, kwargs.get("exact_count"))) or
            {"success": True, "results": [{"path": "docs/CODE_INDEX.md", "text": "index budget"}],
             "count_exact": False, "total_matches": None, "truncated": True}
        ),
    )

    result = service.repo_search(".", "Jak nastavit limit code indexu?", search_mode="hybrid")

    expanded = (
        "Jak nastavit limit code indexu? how configure size index code_index max_index_bytes "
        "database storage eviction maximum bytes"
    )
    assert rag_calls == [expanded]
    assert lexical_calls == [(expanded, False)]
    assert result["query_expansion_applied"] is True
    fused, _ = fuse_search_results(
        [{"path": "src/repo_search.py"}],
        [{"path": "docs/unrelated.md"}],
        limit=10,
        offset=0,
        lexical_first=True,
    )
    assert [item["path"] for item in fused] == ["src/repo_search.py", "docs/unrelated.md"]


def test_lexical_search_skips_large_code_index_candidate_scan(tmp_path, monkeypatch):
    calls = []
    source = tmp_path / "src" / "local_ai_hub" / "services.py"
    source.parent.mkdir(parents=True)
    source.write_text("def search_source(): pass\n", encoding="utf-8")

    class RepoTools:
        ignore_dirs = set()

        def search(self, *_args, **kwargs):
            if kwargs.get("exact_count") is False:
                return {"success": True, "results": [{"path": "src/local_ai_hub/services.py"}],
                        "total_matches": None, "count_exact": False, "truncated": True,
                        "has_more": True}
            return {"success": True, "results": [], "total_matches": 0, "count_exact": True}

    class CandidateIndex:
        def __init__(self, source):
            self.source = source

        def related_paths(self, root, query, limit):
            calls.append((self.source, query))
            return []

        def candidate_paths(self, root, query, limit):
            calls.append((self.source, query))
            return []

    service = object.__new__(LocalAIServices)
    service.config = {}
    service.repo_tools = RepoTools()
    service.code_index = CandidateIndex("code")
    service.deterministic = CandidateIndex("deterministic")
    service.preprocessor = CandidateIndex("preprocess")
    service.learner = None
    service.evidence_store = None
    monkeypatch.setattr(service, "_repo_cache_state", lambda _root: {})
    monkeypatch.setattr(service, "_repo_cached", lambda _op, _root, _params, compute: compute())

    bounded = service._repo_search_lexical(
        str(tmp_path), "Local AI Hub installation", exact_count=False
    )
    assert bounded["success"] is True
    assert bounded["count_exact"] is False
    assert bounded["total_matches"] is None
    assert bounded["candidate_count"] == 1
    assert calls == []

    service._repo_search_lexical(str(tmp_path), "Local AI Hub installation")
    assert calls == []

    service._repo_search_lexical(str(tmp_path), "repo_search")
    assert calls == [("deterministic", "repo_search"), ("preprocess", "repo_search")]


def test_rag_mode_never_claims_exact_corpus_count(monkeypatch):
    service = _service(monkeypatch, [{"path": "src/a.py", "text": "meaning"}])
    result = service.repo_search(".", "installation", search_mode="rag", limit=5)

    assert result["success"] is True
    assert result["count_exact"] is False
    assert result["total_matches"] is None
    assert result["coverage_complete"] is False
    assert result["result_source"] == "rag"


def test_symbol_like_rag_candidates_must_contain_exact_literal(monkeypatch):
    service = _service(monkeypatch, [
        {"path": "src/nearby.py", "text": "a semantically nearby parser"},
        {"path": "docs/CXX.md", "text": "The C++ parser is supported."},
    ])
    result = service.repo_search(".", "C++", search_mode="rag", limit=10)

    assert [row["path"] for row in result["results"]] == ["docs/CXX.md"]
    assert result["result_source"] == "rag"
    assert result["count_exact"] is False


def test_unknown_symbol_does_not_surface_semantic_noise_in_hybrid(monkeypatch):
    service = _service(monkeypatch, [
        {"path": "src/nearby.py", "text": "a semantically nearby parser"},
    ])
    monkeypatch.setattr(service, "_repo_search_lexical", lambda *args, **kwargs: {
        "success": True, "results": [], "total_matches": None,
        "count_exact": False, "truncated": False,
    })

    result = service.repo_search(
        ".", "unknown_agent_symbol_2048", search_mode="hybrid", limit=10,
    )

    assert result["results"] == []
    assert result["rag_candidate_count"] == 0


def test_hybrid_keeps_lexical_exact_count_separate_and_deduplicates(monkeypatch):
    service = _service(monkeypatch, [
        {"path": "src/a.py", "text": "semantic"},
        {"path": "docs/install.md", "text": "setup"},
    ])
    monkeypatch.setattr(service, "_repo_search_lexical", lambda *args, **kwargs: {
        "success": True, "results": [{"path": "src/a.py", "text": "exact"}],
        "total_matches": 37, "count_exact": True,
    })

    result = service.repo_search(".", "Local AI Hub installation", search_mode="hybrid", limit=10)

    assert result["success"] is True
    assert result["count_exact"] is False
    assert result["total_matches"] is None
    assert result["lexical_total_matches"] == 37
    assert result["lexical_count_exact"] is True
    assert len(result["results"]) == 2
    merged = next(row for row in result["results"] if row["path"] == "src/a.py")
    assert merged["sources"] == ["lexical", "rag"]
    assert merged["text"] == "exact"


def test_hybrid_requests_bounded_lexical_candidates_without_exact_corpus_count(monkeypatch):
    service = _service(monkeypatch, [{"path": "docs/install.md", "text": "install"}])
    calls = []

    def lexical(*_args, **kwargs):
        calls.append(kwargs)
        return {"success": True, "results": [{"path": "src/setup.py"}],
                "total_matches": None, "count_exact": False, "truncated": True}

    monkeypatch.setattr(service, "_repo_search_lexical", lexical)

    result = service.repo_search(".", "Local AI Hub installation", search_mode="hybrid", limit=10)

    assert calls[0]["exact_count"] is False
    assert result["count_exact"] is False
    assert result["total_matches"] is None
    assert result["candidate_count"] == 2


def test_hybrid_rag_failure_preserves_exact_lexical_page(monkeypatch):
    service = _service(monkeypatch, rag_meta={"success": False, "reason": "rag_index_missing"})
    calls = []

    def lexical(*args, **kwargs):
        calls.append(kwargs)
        return {"success": True, "results": [{"path": "src/2.py"}],
                "total_matches": 31, "count_exact": True, "offset": kwargs["offset"], "limit": kwargs["limit"]}

    monkeypatch.setattr(service, "_repo_search_lexical", lexical)
    result = service.repo_search(".", "identifier", search_mode="hybrid", limit=1, offset=2)

    assert result["results"] == [{"path": "src/2.py", "sources": ["lexical"], "result_source": "lexical_fallback"}]
    assert result["total_matches"] == 31
    assert result["count_exact"] is True
    assert result["degraded"] is True
    assert calls[0]["offset"] == 2


def test_hybrid_degraded_empty_rag_candidates_use_exact_lexical_page(monkeypatch):
    service = _service(monkeypatch, rag_rows=[], rag_meta={
        "success": True, "degraded": True, "degradation_reason": "embedding_space_mismatch",
        "index_state": "stale", "reranker": {"requested": True, "used": False, "degraded": True},
    })
    monkeypatch.setattr(service, "_repo_search_lexical", lambda *args, **kwargs: {
        "success": True, "results": [{"path": "docs/install.md"}],
        "total_matches": 14, "count_exact": True, "has_more": True,
        "offset": kwargs["offset"], "limit": kwargs["limit"],
    })

    result = service.repo_search(".", "Local AI Hub installation", search_mode="hybrid", limit=1, offset=3)

    assert result["result_source"] == "lexical_fallback"
    assert result["degradation_reason"] == "embedding_space_mismatch"
    assert result["total_matches"] == result["lexical_total_matches"] == 14
    assert result["count_exact"] is True
    assert result["results"][0]["sources"] == ["lexical"]


def test_invalid_search_mode_rejects(monkeypatch):
    service = _service(monkeypatch)
    result = service.repo_search(".", "x", search_mode="semantic")
    assert result["status_code"] == 400
    assert result["terminal"] is True


def test_rag_candidates_are_checked_against_current_source_and_policy(tmp_path):
    source = tmp_path / "current.py"
    source.write_text("def install_hub():\n    return True\n", encoding="utf-8")

    class FakeRag:
        def workspace_id(self, root):
            return "repo:test"

        def require_workspace_root(self, *, workspace, root):
            assert workspace == "repo:test"
            assert root == str(tmp_path)

        def list_workspaces(self):
            return [{"workspace": "repo:test", "files": 1}]

        def revision(self, *, workspace):
            return "rev-1"

        def search(self, query, **kwargs):
            assert kwargs["semantic_only"] is True
            assert kwargs["workspace"] == "repo:test"
            return {"success": True, "index_revision": "rev-1", "reranked": False, "results": [
                {"path": "current.py", "text": "def install_hub():\n    return True\n"},
                {"path": "../outside.py", "text": "outside"},
            ]}

        def project_context(self, root):
            return None

        def _project_path_decision(self, root, path, project_context, *, phase, size_bytes):
            assert phase == "search"
            return True, "text"

    service = object.__new__(LocalAIServices)
    service.config = {"features": {"rag": True, "reranker": False}, "rag": {"max_file_bytes": 1000}}
    service.rag = FakeRag()

    rows, meta = service._repo_rag_search(str(tmp_path), "installation", 8)

    assert [row["path"] for row in rows] == ["current.py"]
    assert meta["index_revision"] == "rev-1"
    assert meta["candidate_freshness"] == "verified_against_current_sources"


def test_stale_rag_candidate_is_dropped_and_reported(tmp_path):
    (tmp_path / "current.py").write_text("new source", encoding="utf-8")

    class FakeRag:
        def workspace_id(self, root): return "repo:test"
        def require_workspace_root(self, *, workspace, root): pass
        def list_workspaces(self): return [{"workspace": "repo:test", "files": 1}]
        def revision(self, *, workspace): return "rev-1"
        def search(self, query, **kwargs):
            return {"success": True, "index_revision": "rev-1", "results": [{"path": "current.py", "text": "removed source"}]}
        def project_context(self, root): return None
        def _project_path_decision(self, root, path, project_context, *, phase, size_bytes):
            return True, "text"

    service = object.__new__(LocalAIServices)
    service.config = {"features": {"rag": True, "reranker": False}, "rag": {"max_file_bytes": 1000}}
    service.rag = FakeRag()
    rows, meta = service._repo_rag_search(str(tmp_path), "old source", 8)

    assert rows == []
    assert meta["degraded"] is True
    assert meta["index_state"] == "stale"
    assert meta["stale_candidate_count"] == 1


def test_ast_chunk_module_context_is_verified_against_current_source(tmp_path):
    source = (
        "from pathlib import Path\n\n"
        "class IndexBudget:\n"
        "    def enforce(self):\n"
        "        return Path('state.sqlite3')\n"
    )
    (tmp_path / "budget.py").write_text(source, encoding="utf-8")
    ast_chunk = (
        "# [Module context]\nfrom pathlib import Path\n\n"
        "class IndexBudget:\n    # method enforce\n"
        "    def enforce(self):\n        return Path('state.sqlite3')"
    )

    class FakeRag:
        def workspace_id(self, root): return "repo:test"
        def require_workspace_root(self, *, workspace, root): pass
        def list_workspaces(self): return [{"workspace": "repo:test", "files": 1}]
        def revision(self, *, workspace): return "rev-1"
        def search(self, query, **kwargs):
            return {"success": True, "index_revision": "rev-1", "results": [
                {"path": "budget.py", "text": ast_chunk},
            ]}
        def project_context(self, root): return None
        def _project_path_decision(self, root, path, project_context, *, phase, size_bytes):
            return True, "text"

    service = object.__new__(LocalAIServices)
    service.config = {"features": {"rag": True, "reranker": False}, "rag": {"max_file_bytes": 1000}}
    service.rag = FakeRag()

    rows, meta = service._repo_rag_search(str(tmp_path), "index size", 8)

    assert [row["path"] for row in rows] == ["budget.py"]
    assert meta["stale_candidate_count"] == 0
    assert meta["index_state"] == "available"


def test_empty_rag_workspace_skips_embedding_search(tmp_path):
    calls = []

    class EmptyRag:
        def workspace_id(self, root):
            return "repo:empty"

        def require_workspace_root(self, *, workspace, root):
            assert workspace == "repo:empty"
            assert root == str(tmp_path)

        def list_workspaces(self):
            return []

        def has_workspace_chunks(self, *, workspace):
            assert workspace == "repo:empty"
            return False

        def search(self, query, **kwargs):
            calls.append((query, kwargs))
            return {"success": True, "results": []}

    service = object.__new__(LocalAIServices)
    service.config = {"features": {"rag": True, "reranker": True}}
    service.rag = EmptyRag()

    rows, meta = service._repo_rag_search(str(tmp_path), "installation", 8)

    assert rows == []
    assert calls == []
    assert meta["success"] is False
    assert meta["reason"] == "rag_index_missing"
    assert meta["index_state"] == "missing"
