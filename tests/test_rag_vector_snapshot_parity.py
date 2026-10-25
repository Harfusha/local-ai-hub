from __future__ import annotations

from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.rag import RAGStore
from local_ai_hub.sqlite_support import connect_sqlite


@pytest.fixture
def rag_with_chunks(tmp_path: Path) -> tuple[RAGStore, str]:
    db_path = str(tmp_path / "rag.db")
    config = {
        "server": {"state_dir": str(tmp_path)},
        "rag": {"db_path": db_path},
    }
    rag = RAGStore(config)
    rag._init_db()

    workspace = "test_ws"
    # Pre-populate 500 chunks with varying token overlaps and ties
    with closing(connect_sqlite(rag.db_path)) as con:
        rows = [
            (
                workspace,
                f"src/file_{i}.py",
                i,
                f"def function_{i}(): return 'foo bar' if {i % 2 == 0} else 'foo' if {i % 3 == 0} else 'none'",
                f"hash_{i}",
                "default_space",
                b"",
            )
            for i in range(500)
        ]
        con.executemany(
            """
            INSERT INTO chunks (workspace, path, chunk_no, text, content_hash, embedding_space, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        con.commit()

    return rag, workspace


def test_token_overlap_streaming_heap_exact_ranking_and_ties(rag_with_chunks: tuple[RAGStore, str]):
    rag, ws = rag_with_chunks

    # Query with multiple matching terms
    results = rag._search_token_overlap("foo bar", ws, limit=10)
    assert len(results) == 10

    # Top results should have both 'foo' and 'bar' (score 1.0)
    for r in results:
        assert r["fts_score"] == 1.0
        assert "foo" in r["text"].lower()
        assert "bar" in r["text"].lower()

    # Verify tie order: smaller chunk_no / earlier seen must come first
    chunk_numbers = [r["chunk_no"] for r in results]
    assert chunk_numbers == sorted(chunk_numbers), "Tie order must stably preserve row sequence"


def test_token_overlap_zero_or_negative_limit(rag_with_chunks: tuple[RAGStore, str]):
    rag, ws = rag_with_chunks
    assert rag._search_token_overlap("foo", ws, limit=0) == []
    assert rag._search_token_overlap("foo", ws, limit=-5) == []
    assert rag._search_token_overlap("", ws, limit=10) == []


def test_token_overlap_scoped_path_filtering(rag_with_chunks: tuple[RAGStore, str]):
    rag, ws = rag_with_chunks

    # Query scoped to file_0.py
    results = rag._search_token_overlap("foo", ws, limit=10, scope_path="src/file_0.py")
    assert len(results) == 1
    assert results[0]["path"] == "src/file_0.py"

    # Query scoped to nonexistent file
    results = rag._search_token_overlap("foo", ws, limit=10, scope_path="src/nonexistent.py")
    assert len(results) == 0
