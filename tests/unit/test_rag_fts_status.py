from __future__ import annotations

import sqlite3
from pathlib import Path

from local_ai_hub.rag import RAGStore


def _store(db_path: Path, *, with_fts: bool) -> RAGStore:
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE chunks(workspace TEXT, path TEXT, chunk_no INTEGER, text TEXT, content_hash TEXT, embedding_space TEXT)"
    )
    if with_fts:
        connection.execute(
            "CREATE VIRTUAL TABLE chunk_fts USING fts5(workspace UNINDEXED, path UNINDEXED, chunk_no UNINDEXED, text)"
        )
    connection.commit()
    connection.close()
    store = RAGStore.__new__(RAGStore)
    store._connect = lambda: sqlite3.connect(db_path)
    return store


def test_valid_empty_fts_index_is_distinct_from_unavailable_index(tmp_path: Path) -> None:
    empty = _store(tmp_path / "empty.sqlite", with_fts=True)
    unavailable = _store(tmp_path / "missing.sqlite", with_fts=False)

    assert empty._search_fts_candidates("alpha beta", "workspace")["status"] == "MATCHES_EMPTY"
    assert unavailable._search_fts_candidates("alpha beta", "workspace")["status"] == "FTS_UNAVAILABLE"


def test_fts_search_returns_typed_matches(tmp_path: Path) -> None:
    store = _store(tmp_path / "matches.sqlite", with_fts=True)
    connection = sqlite3.connect(tmp_path / "matches.sqlite")
    try:
        connection.execute(
            "INSERT INTO chunks VALUES(?, ?, ?, ?, ?, ?)",
            ("workspace", "src/example.py", 0, "alpha beta content", "hash", "space"),
        )
        connection.execute(
            "INSERT INTO chunk_fts VALUES(?, ?, ?, ?)",
            ("workspace", "src/example.py", 0, "alpha beta content"),
        )
        connection.commit()
    finally:
        connection.close()

    result = store._search_fts_candidates("alpha beta", "workspace")

    assert result["status"] == "MATCHES_FOUND"
    assert result["candidates"][0]["path"] == "src/example.py"
    assert result["candidates"][0]["content_hash"] == "hash"


def test_fts_failure_classifier_preserves_failure_category() -> None:
    assert RAGStore._fts_error_status(sqlite3.OperationalError("database is locked")) == "FTS_TIMEOUT/LOCKED"
    assert RAGStore._fts_error_status(sqlite3.DatabaseError("database disk image is malformed")) == "FTS_INDEX_CORRUPT"
    assert RAGStore._fts_error_status(sqlite3.OperationalError("fts5 syntax error")) == "FTS_QUERY_INVALID"
