from __future__ import annotations

import sqlite3

from local_ai_hub.rag import RAGStore
from local_ai_hub.search_fusion import fuse_search_candidates
from local_ai_hub.services import LocalAIServices


def test_search_pipeline_keeps_source_provenance_and_truthful_fallback(monkeypatch) -> None:
    fused = fuse_search_candidates(
        [{"path": "src/access.py", "chunk_id": "lex-1", "content_hash": "l", "text": "access key"}],
        [{"path": "src/access.py", "chunk_id": "sem-2", "content_hash": "s", "text": "renew access key", "relevance": 0.9}],
    )
    assert fused[0]["sources"] == ["lexical", "semantic"]
    assert fused[0]["primary_match"]["text"] == "renew access key"
    assert {match["chunk_id"] for match in fused[0]["matches"]} == {"lex-1", "sem-2"}
    assert fused[0]["source_breakdown"].keys() == {"lexical", "semantic"}


def test_search_identity_is_host_independent_and_keeps_git_case(monkeypatch) -> None:
    fused = fuse_search_candidates(
        [
            {"path": r"./src\\Access.py", "chunk_id": "one", "content_hash": "a", "text": "lower path"},
            {"path": "Src/Access.py", "chunk_id": "two", "content_hash": "b", "text": "upper path"},
            {"path": "src/../outside.py", "chunk_id": "bad", "content_hash": "c", "text": "escape"},
        ],
        [],
    )
    assert [item["path"] for item in fused] == ["src/Access.py", "Src/Access.py"]
    assert fuse_search_candidates(
        [{"path": "Src/Access.py", "chunk_id": "one", "content_hash": "a", "text": "one"}],
        [{"path": "src/access.py", "chunk_id": "two", "content_hash": "b", "text": "two"}],
        case_sensitive=False,
    )[0]["sources"] == ["lexical", "semantic"]


def test_search_fusion_preserves_alternatives_and_deduplicates_identical_chunks() -> None:
    fused = fuse_search_candidates(
        [
            {"path": "src/Checkout.php", "source_id": "repo", "chunk_id": "method-a", "content_hash": "hash-a", "text": "wrong method", "relevance": 0.1},
            {"path": "src/Checkout.php", "source_id": "repo", "chunk_id": "method-b", "content_hash": "hash-b", "text": "second method", "relevance": 0.4},
            {"path": "src/Checkout.php", "source_id": "repo", "chunk_id": "method-d", "content_hash": "hash-d", "text": "unrelated method", "relevance": 0.05},
        ],
        [
            {"path": "src/Checkout.php", "source_id": "repo", "chunk_id": "method-a", "content_hash": "hash-a", "text": "wrong method", "relevance": 0.2},
            {"path": "src/Checkout.php", "source_id": "repo", "chunk_id": "method-c", "content_hash": "hash-c", "text": "target method", "relevance": 0.9},
        ],
        limit=1,
        matches_per_file=3,
    )

    assert len(fused) == 1
    assert fused[0]["primary_match"]["chunk_id"] == "method-c"
    assert fused[0]["alternative_matches"][0]["chunk_id"] == "method-b"
    duplicate = next(match for match in fused[0]["matches"] if match["chunk_id"] == "method-a")
    assert duplicate["sources"] == ["lexical", "semantic"]
    assert fused[0]["truncated"] is True
    assert fused[0]["omitted_matches"] == 1


def test_search_pipeline_keeps_truthful_fallback(monkeypatch) -> None:
    service = object.__new__(LocalAIServices)
    service.config = {"features": {"rag": True}}
    monkeypatch.setattr(
        service,
        "_repo_rag_search",
        lambda *_args, **_kwargs: ([], {"success": False, "reason": "embedding_backend", "index_state": "unavailable"}),
    )
    monkeypatch.setattr(
        service,
        "_repo_search_lexical",
        lambda root, query, *args, **kwargs: {
            "success": True,
            "root": root,
            "results": [{"path": "src/access.py", "text": "def renew_access_key():"}],
            "total_matches": 1,
            "count_exact": False,
            "has_more": False,
        },
    )

    result = service.repo_search("C:/repo", "how to renew an access key", search_mode="hybrid", limit=5)

    assert result["result_source"] == "lexical_fallback"
    assert result["coverage_complete"] is False
    assert result["total_matches"] is None and result["count_exact"] is False
    assert result["results"][0]["path"] == "src/access.py"


def test_search_fts_unavailable_is_distinct_from_empty_index(tmp_path) -> None:
    db_path = tmp_path / "without-fts.sqlite"
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE chunks(workspace TEXT, path TEXT, chunk_no INTEGER, text TEXT, content_hash TEXT, embedding_space TEXT)"
    )
    connection.close()
    store = RAGStore.__new__(RAGStore)
    store._connect = lambda: sqlite3.connect(db_path)

    assert store._search_fts_candidates("alpha beta", "workspace")["status"] == "FTS_UNAVAILABLE"
