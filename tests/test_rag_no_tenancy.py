from __future__ import annotations

import hashlib
import inspect
import sqlite3
from contextlib import closing

import pytest

from local_ai_hub.rag import RAGStore


def _config(state_dir) -> dict:
    return {
        "server": {"state_dir": str(state_dir)},
        "models": {},
        "cpu_retrieval": {},
        "workspace_cache": {},
        "rag": {"extensions": [".md"], "ignore_dirs": []},
        "resilience": {"singleflight_wait_timeout_seconds": 1},
    }


def test_rag_contract_has_workspace_only_public_scope() -> None:
    for name in ("index", "index_step", "search", "revision", "remove_paths", "remove_project", "index_paths_step", "ingest_document", "ingest_diagram"):
        signature = inspect.signature(getattr(RAGStore, name))
        assert "tenant" not in signature.parameters
        assert signature.parameters["workspace"].kind is inspect.Parameter.KEYWORD_ONLY

    assert "tenant" not in inspect.signature(RAGStore.list_workspaces).parameters
    assert "tenant" not in inspect.signature(RAGStore.docset_index).parameters
    assert "tenant" not in inspect.signature(RAGStore.docset_search).parameters
    assert inspect.signature(RAGStore.docset_index).parameters["root"].kind is inspect.Parameter.KEYWORD_ONLY
    assert inspect.signature(RAGStore.docset_search).parameters["query"].kind is inspect.Parameter.KEYWORD_ONLY


def test_new_rag_schema_has_no_tenant_columns(tmp_path) -> None:
    store = RAGStore(_config(tmp_path / "state"))
    with closing(sqlite3.connect(store.db_path)) as connection, connection:
        for table in ("chunks", "files", "project_file_owners", "chunk_fts"):
            columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            assert "tenant" not in columns


def test_tenant_schema_rejected_without_database_mutation(tmp_path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    database = state_dir / "rag.sqlite3"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            "CREATE TABLE chunks (tenant TEXT NOT NULL, workspace TEXT NOT NULL, "
            "path TEXT NOT NULL, chunk_no INTEGER NOT NULL, content_hash TEXT NOT NULL, "
            "text TEXT NOT NULL, embedding TEXT NOT NULL, PRIMARY KEY (workspace,  path, chunk_no))"
        )
        connection.execute(
            "INSERT INTO chunks VALUES ('legacy-owner', 'repo:one', 'a.md', 0, 'hash', 'body', '[]')"
        )

    before = hashlib.sha256(database.read_bytes()).digest()
    with pytest.raises(RuntimeError, match="explicit offline conversion required"):
        RAGStore(_config(state_dir))
    assert hashlib.sha256(database.read_bytes()).digest() == before
    with closing(sqlite3.connect(database)) as connection, connection:
        row = connection.execute("SELECT workspace,  path, text FROM chunks").fetchone()
    assert row == ("repo:one", "a.md", "body")


def test_incompatible_non_tenant_schema_is_preserved(tmp_path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    database = state_dir / "rag.sqlite3"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.executescript(
            "CREATE TABLE chunks (workspace TEXT, path TEXT, chunk_no INTEGER, "
            "content_hash TEXT, text TEXT, embedding TEXT);"
            "CREATE TABLE files (workspace TEXT, path TEXT, mtime_ns INTEGER, size INTEGER, content_hash TEXT);"
            "CREATE TABLE project_file_owners (workspace TEXT, root TEXT, path TEXT);"
            "CREATE TABLE rag_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "INSERT INTO chunks VALUES ('repo:one', 'a.md', 0, 'hash', 'body', '[]');"
        )
    before = hashlib.sha256(database.read_bytes()).digest()
    with pytest.raises(RuntimeError, match="explicit offline conversion required"):
        RAGStore(_config(state_dir))
    assert hashlib.sha256(database.read_bytes()).digest() == before
    assert not (state_dir / "cache.sqlite").exists()


@pytest.mark.parametrize("stored_fingerprint", [None, "obsolete-fingerprint"])
def test_existing_content_with_missing_or_changed_fingerprint_is_preserved(
    tmp_path, stored_fingerprint: str | None,
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    database = state_dir / "rag.sqlite3"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.executescript(
            "CREATE TABLE chunks (workspace TEXT NOT NULL, path TEXT NOT NULL, chunk_no INTEGER NOT NULL, "
            "content_hash TEXT NOT NULL, text TEXT NOT NULL, embedding TEXT NOT NULL, "
            "embedding_space TEXT NOT NULL DEFAULT '', PRIMARY KEY (workspace,path,chunk_no));"
            "CREATE TABLE files (workspace TEXT NOT NULL, path TEXT NOT NULL, mtime_ns INTEGER NOT NULL, "
            "size INTEGER NOT NULL, content_hash TEXT NOT NULL, PRIMARY KEY (workspace,path));"
            "CREATE TABLE project_file_owners (workspace TEXT NOT NULL, root TEXT NOT NULL, path TEXT NOT NULL, "
            "PRIMARY KEY (workspace,root,path));"
            "CREATE TABLE rag_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "INSERT INTO chunks VALUES ('repo:one', 'a.md', 0, 'hash', 'body', '[]', 'space-v1');"
        )
        if stored_fingerprint is not None:
            connection.execute(
                "INSERT INTO rag_meta VALUES ('index_fingerprint', ?)", (stored_fingerprint,)
            )
    before = hashlib.sha256(database.read_bytes()).digest()
    with pytest.raises(RuntimeError, match="fingerprint|offline rebuild"):
        RAGStore(_config(state_dir))
    assert hashlib.sha256(database.read_bytes()).digest() == before
    assert not (state_dir / "cache.sqlite").exists()


def test_corrupt_database_and_sidecars_are_preserved(tmp_path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    database = state_dir / "rag.sqlite3"
    database.write_bytes(b"not a sqlite database")
    wal = state_dir / "rag.sqlite3-wal"
    shm = state_dir / "rag.sqlite3-shm"
    wal.write_bytes(b"preserve wal")
    shm.write_bytes(b"preserve shm")
    before = [hashlib.sha256(path.read_bytes()).digest() for path in (database, wal, shm)]
    with pytest.raises(RuntimeError, match="original database and sidecars were preserved"):
        RAGStore(_config(state_dir))
    assert [hashlib.sha256(path.read_bytes()).digest() for path in (database, wal, shm)] == before
    assert not (state_dir / "cache.sqlite").exists()
