from __future__ import annotations

from pathlib import Path

from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices


def test_hybrid_uses_expanded_query_for_bounded_lexical_candidates(monkeypatch):
    service = object.__new__(LocalAIServices)
    service.config = {"features": {"rag": True, "reranker": False}}
    service._repo_rag_search = lambda _root, query, _top_k: (
        [{"path": "docs/agent-evaluation/results.md", "text": "index budget"}],
        {"success": True, "index_state": "current", "degraded": False},
    )
    service.preprocessor = type(
        "Preprocessor",
        (),
        {"candidate_paths": lambda _self, _root, _query, _limit: ["docs/CODE_INDEX.md"]},
    )()
    lexical_calls = []
    service._repo_search_lexical = lambda _root, query, *_args, **kwargs: (
        lexical_calls.append((query, kwargs))
        or {
            "success": True,
            "results": [
                {"path": "docs/CODE_INDEX.md", "text": "code index size limit"},
                {"path": "docs/CODE_INDEX.md", "text": "duplicate matching line"},
                {"path": "src/local_ai_hub/code_index.py", "text": "budget eviction"},
            ],
            "total_matches": None,
            "count_exact": False,
        }
    )

    result = service.repo_search(
        "C:/repo",
        "Jak omezit velikost code indexu?",
        search_mode="hybrid",
        limit=10,
    )

    assert lexical_calls[0][0] == "Jak omezit velikost code indexu?"
    assert lexical_calls[0][1]["exact_count"] is False
    assert lexical_calls[0][1]["candidate_paths"] == ("docs/CODE_INDEX.md",)
    assert lexical_calls[0][1]["candidate_query"] == (
        "code_index max_index_bytes eviction byte budget"
    )
    assert result["query_expansion_applied"] is True
    assert result["lexical_count_exact"] is False
    assert result["results"][0]["path"] == "docs/CODE_INDEX.md"


def test_repository_search_matches_expanded_terms_but_keeps_original_phrase(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "CODE_INDEX.md").write_text(
        "Set max_index_bytes to bound code_index storage and eviction.\n",
        encoding="utf-8",
    )

    result = RepositoryTools({}).search(
        str(tmp_path),
        "Jak omezit velikost code indexu?",
        candidate_paths=["docs/CODE_INDEX.md"],
        candidate_query="code_index max_index_bytes eviction",
        limit=5,
        exact_count=False,
    )

    assert result["success"] is True
    assert result["results"]
    assert result["results"][0]["path"] == "docs/CODE_INDEX.md"
    assert "jak" not in result["terms"]
    assert "omezit" not in result["terms"]
    assert "indexu" not in result["terms"]
    assert "max_index_bytes" in result["terms"]


def test_hybrid_degrades_to_bounded_expanded_candidates_when_rag_is_stale(monkeypatch):
    service = object.__new__(LocalAIServices)
    service.config = {"features": {"rag": True, "reranker": True}}
    service._repo_rag_search = lambda _root, _query, _top_k: (
        [],
        {
            "success": False,
            "reason": "embedding_space_mismatch",
            "index_state": "stale",
        },
    )
    service.preprocessor = type(
        "Preprocessor",
        (),
        {"candidate_paths": lambda _self, _root, _query, _limit: ["docs/CODE_INDEX.md"]},
    )()
    lexical_calls = []
    service._repo_search_lexical = lambda _root, query, *_args, **kwargs: (
        lexical_calls.append((query, kwargs))
        or {
            "success": True,
            "results": [
                {"path": "docs/CODE_INDEX.md", "text": "code index size limit"},
                {"path": "docs/CODE_INDEX.md", "text": "duplicate matching line"},
                {"path": "src/local_ai_hub/code_index.py", "text": "budget eviction"},
            ],
            "candidate_count": 3,
            "total_matches": None,
            "count_exact": False,
        }
    )

    result = service.repo_search(
        "C:/repo",
        "Jak omezit velikost code indexu?",
        search_mode="hybrid",
        limit=10,
    )

    assert lexical_calls[0][0] == "Jak omezit velikost code indexu?"
    assert lexical_calls[0][1]["candidate_query"].endswith(
        "code_index max_index_bytes eviction byte budget"
    )
    assert result["success"] is True
    assert result["result_source"] == "lexical_fallback"
    assert result["degraded"] is True
    assert result["degradation_reason"] == "embedding_space_mismatch"
    assert result["coverage_complete"] is False
    assert result["count_exact"] is False
    assert result["total_matches"] is None
    assert result["results"][0]["path"] == "docs/CODE_INDEX.md"
    assert [item["path"] for item in result["results"]] == [
        "docs/CODE_INDEX.md", "src/local_ai_hub/code_index.py",
    ]


def test_hybrid_stale_rag_uses_expanded_current_source_scan_without_index_paths(monkeypatch):
    service = object.__new__(LocalAIServices)
    service.config = {"features": {"rag": True, "reranker": True}}
    service._repo_rag_search = lambda _root, _query, _top_k: (
        [],
        {"success": False, "reason": "embedding_space_mismatch", "index_state": "stale"},
    )
    service.preprocessor = type(
        "Preprocessor", (), {"candidate_paths": lambda _self, _root, _query, _limit: []},
    )()
    lexical_calls = []
    service._repo_search_lexical = lambda _root, query, *_args, **kwargs: (
        lexical_calls.append((query, kwargs))
        or {
            "success": True,
            "results": [{"path": "docs/INSTALLATION.md", "text": "install setup"}],
            "candidate_count": 1,
            "total_matches": None,
            "count_exact": False,
        }
    )

    result = service.repo_search(
        "C:/repo", "Local AI Hub installation", search_mode="hybrid", limit=5,
    )

    assert lexical_calls[0][0] == "Local AI Hub installation"
    assert lexical_calls[0][1]["candidate_query"].endswith("install setup getting started bootstrap")
    assert lexical_calls[0][1]["candidate_paths"] is None
    assert lexical_calls[0][1]["exact_count"] is False
    assert result["lexical_candidate_source"] == "current_source_scan"
    assert result["lexical_preprocessed_candidate_count"] == 0
    assert result["count_exact"] is False


def test_hybrid_empty_degraded_rag_uses_the_same_expanded_fallback(monkeypatch):
    service = object.__new__(LocalAIServices)
    service.config = {"features": {"rag": True, "reranker": True}}
    service._repo_rag_search = lambda _root, _query, _top_k: (
        [],
        {
            "success": True,
            "degraded": True,
            "degradation_reason": "embedding_space_mismatch",
            "index_state": "stale",
        },
    )
    service.preprocessor = type(
        "Preprocessor", (), {"candidate_paths": lambda _self, _root, _query, _limit: []},
    )()
    lexical_calls = []
    service._repo_search_lexical = lambda _root, query, *_args, **kwargs: (
        lexical_calls.append((query, kwargs))
        or {
            "success": True,
            "results": [{"path": "docs/INSTALLATION.md", "text": "install setup"}],
            "candidate_count": 1,
            "total_matches": None,
            "count_exact": False,
        }
    )

    result = service.repo_search(
        "C:/repo", "Local AI Hub installation", search_mode="hybrid", limit=5,
    )

    assert lexical_calls[0][1]["candidate_query"].endswith("install setup getting started bootstrap")
    assert lexical_calls[0][1]["exact_count"] is False
    assert result["result_source"] == "lexical_fallback"
    assert result["query_expansion_applied"] is True
    assert result["degraded"] is True
    assert result["count_exact"] is False
    assert result["total_matches"] is None
