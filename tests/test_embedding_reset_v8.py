from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from tools.embedding_reset import (
    apply_embedding_reset, clear_embedding_payloads, restore_embedding_reset_backup, verify_embedding_reset,
)


def _db(path: Path, ddl: str, rows: str) -> None:
    with closing(sqlite3.connect(path)) as con:
        con.executescript(ddl)
        con.executescript(rows)
        con.commit()


def _state(root: Path) -> None:
    _db(root / "rag.sqlite3", """
        CREATE TABLE chunks(workspace TEXT,path TEXT,chunk_no INTEGER,content_hash TEXT,text TEXT,embedding TEXT NOT NULL,embedding_space TEXT NOT NULL);
        CREATE TABLE content_rag_chunks(content_hash TEXT,embedding_space TEXT,chunk_index INTEGER,chunk_text TEXT,embedding_blob BLOB NOT NULL,created_at REAL);
        CREATE TABLE rag_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE files(workspace TEXT,path TEXT,mtime_ns INTEGER,size INTEGER,content_hash TEXT);
        CREATE TABLE project_file_owners(workspace TEXT,root TEXT,path TEXT);
    """, """
        INSERT INTO chunks VALUES('w','a.py',0,'h','preserve text','[0.1,0.2]','old-space');
        INSERT INTO content_rag_chunks VALUES('h','old-space',0,'preserve content',X'010203',1);
        INSERT INTO content_rag_chunks VALUES('h','other-space',0,'preserve content',X'040506',1);
        INSERT INTO rag_meta VALUES('index_fingerprint','old-fingerprint');
        INSERT INTO rag_meta VALUES('workspace_embedding_space:w','old-space');
        INSERT INTO rag_meta VALUES('workspace_reindex_target:w','older-space');
        INSERT INTO files VALUES('w','a.py',1,14,'h');
        INSERT INTO project_file_owners VALUES('w','C:/repo','a.py');
    """)
    _db(root / "cache.sqlite", "CREATE TABLE cache_entries(namespace TEXT,cache_key TEXT,value_json TEXT,created_at REAL,accessed_at REAL,hits INTEGER);", """
        INSERT INTO cache_entries VALUES('7.0.0:embeddings','e','[0.1,0.2]',1,1,0);
        INSERT INTO cache_entries VALUES('7.0.0:commands','keep','{\"ok\":true}',1,1,0);
    """)
    _db(root / "semantic-cache.sqlite3", "CREATE TABLE semantic_entries(id INTEGER PRIMARY KEY,scope_key TEXT,query_hash TEXT,query_text TEXT,vector_blob BLOB NOT NULL,value_json TEXT,created_at REAL,accessed_at REAL,hits INTEGER);", """
        INSERT INTO semantic_entries VALUES(1,'s','q','query',X'010203','{\"answer\":1}',1,1,0);
    """)
    _db(root / "agent_state.sqlite", "CREATE TABLE agent_memory_records(id TEXT PRIMARY KEY,content TEXT); CREATE TABLE agent_memory_embeddings(record_id TEXT,embedding BLOB,created_at REAL,embedding_space_id TEXT,model_name TEXT,dimension INTEGER);", """
        INSERT INTO agent_memory_records VALUES('m','preserve memory');
        INSERT INTO agent_memory_embeddings VALUES('m',X'010203',1,'old-space','fixed-model',2);
    """)


def test_embedding_reset_clears_vectors_preserves_records_and_is_idempotent(tmp_path: Path) -> None:
    _state(tmp_path)
    archived = tmp_path / "recovery" / "rag-before-upgrade" / "rag.sqlite3"
    archived.parent.mkdir(parents=True)
    _db(archived, "CREATE TABLE chunks(embedding TEXT NOT NULL,embedding_space TEXT NOT NULL); CREATE TABLE rag_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);", "INSERT INTO chunks VALUES('[0.4,0.5]','retired-space');")
    legacy_cache = tmp_path / "recovery" / "rag-before-upgrade" / "cache.sqlite3"
    _db(legacy_cache, "CREATE TABLE cache_entries(namespace TEXT,cache_key TEXT,value_json TEXT,created_at REAL,accessed_at REAL,hits INTEGER);", "INSERT INTO cache_entries VALUES('embeddings','old','[0.4,0.5]',1,1,0);")

    first = apply_embedding_reset(tmp_path)
    second = apply_embedding_reset(tmp_path)

    assert first["status"] == "migrated"
    assert second["status"] == "already_applied"
    assert verify_embedding_reset(tmp_path)
    with closing(sqlite3.connect(tmp_path / "rag.sqlite3")) as con:
        assert con.execute("SELECT text,embedding,embedding_space FROM chunks").fetchone() == ("preserve text", "[]", "")
        assert con.execute("SELECT COUNT(*) FROM content_rag_chunks WHERE chunk_text='preserve content' AND embedding_blob=X''").fetchone() == (2,)
        assert con.execute("SELECT value FROM rag_meta WHERE key='workspace_embedding_space:w'").fetchone() is None
        assert con.execute("SELECT value FROM rag_meta WHERE key='workspace_reindex_target:w'").fetchone() is None
        assert con.execute("SELECT path FROM files").fetchone() == ("a.py",)
        assert con.execute("SELECT path FROM project_file_owners").fetchone() == ("a.py",)
    with closing(sqlite3.connect(tmp_path / "cache.sqlite")) as con:
        assert con.execute("SELECT namespace FROM cache_entries").fetchall() == [("7.0.0:commands",)]
    with closing(sqlite3.connect(tmp_path / "semantic-cache.sqlite3")) as con:
        assert con.execute("SELECT vector_blob,value_json FROM semantic_entries").fetchone() == (b"", '{"answer":1}')
    with closing(sqlite3.connect(tmp_path / "agent_state.sqlite")) as con:
        assert con.execute("SELECT content FROM agent_memory_records").fetchone() == ("preserve memory",)
        assert con.execute("SELECT COUNT(*) FROM agent_memory_embeddings").fetchone() == (0,)
    with closing(sqlite3.connect(archived)) as con:
        assert con.execute("SELECT embedding,embedding_space FROM chunks").fetchone() == ("[]", "")
    with closing(sqlite3.connect(legacy_cache)) as con:
        assert con.execute("SELECT COUNT(*) FROM cache_entries").fetchone() == (0,)


def test_embedding_reset_backup_restores_only_affected_database_files(tmp_path: Path) -> None:
    _state(tmp_path)
    archived = tmp_path / "recovery" / "upgrade-7.0" / "rag.sqlite3"
    archived.parent.mkdir(parents=True)
    _db(archived, "CREATE TABLE chunks(embedding TEXT NOT NULL,embedding_space TEXT NOT NULL);", "INSERT INTO chunks VALUES('[0.4,0.5]','old-space');")
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("untouched", encoding="utf-8")

    result = apply_embedding_reset(tmp_path)
    backup = Path(result["backup"])
    unrelated.write_text("changed after reset", encoding="utf-8")
    restore_embedding_reset_backup(tmp_path, backup)

    with closing(sqlite3.connect(tmp_path / "rag.sqlite3")) as con:
        assert con.execute("SELECT embedding FROM chunks").fetchone() == ("[0.1,0.2]",)
    with closing(sqlite3.connect(archived)) as con:
        assert con.execute("SELECT embedding,embedding_space FROM chunks").fetchone() == ("[0.4,0.5]", "old-space")
    assert unrelated.read_text(encoding="utf-8") == "changed after reset"


def test_retained_state_snapshot_is_sanitized_without_restoring_old_vectors(tmp_path: Path) -> None:
    snapshot = tmp_path / "state-snapshot"
    snapshot.mkdir()
    _state(snapshot)
    archived = snapshot / "rag-recovery-before-upgrade" / "rag.sqlite3"
    archived.parent.mkdir()
    _db(archived, "CREATE TABLE chunks(embedding TEXT NOT NULL,embedding_space TEXT NOT NULL);", "INSERT INTO chunks VALUES('[0.8,0.9]','old');")

    assert clear_embedding_payloads(snapshot)
    assert verify_embedding_reset(snapshot)
    with closing(sqlite3.connect(snapshot / "rag.sqlite3")) as con:
        assert con.execute("SELECT COUNT(*) FROM chunks WHERE embedding<>'[]' OR embedding_space<>''").fetchone() == (0,)
    with closing(sqlite3.connect(archived)) as con:
        assert con.execute("SELECT COUNT(*) FROM chunks WHERE embedding<>'[]' OR embedding_space<>''").fetchone() == (0,)


def test_rag_store_tolerates_stale_fingerprint_and_adopts_after_reset(tmp_path: Path) -> None:
    from local_ai_hub.rag import RAGStore

    config = {
        "server": {"state_dir": str(tmp_path)},
        "models": {"embedding": "fixed-model", "embedding_backend": "sentence-transformers", "embedding_device": "cpu"},
        "cpu_retrieval": {},
        "rag": {},
        "workspace_cache": {},
        "resilience": {},
    }
    first = RAGStore(config)
    current = first.index_fingerprint
    with closing(first._connect()) as con:
        con.execute("UPDATE rag_meta SET value='old-fingerprint' WHERE key='index_fingerprint'")
        con.execute("INSERT INTO chunks VALUES('w','a.py',0,'h','source','[0.2]','old-space')")
        con.commit()

    stale = RAGStore(config)
    assert stale.index_fingerprint_mismatch is True
    with closing(stale._connect()) as con:
        con.execute("UPDATE chunks SET embedding='[]',embedding_space=''")
        con.execute("INSERT INTO rag_meta(key,value) VALUES('embedding_reset_version','8.0')")
        con.commit()

    reset = RAGStore(config)
    assert reset.index_fingerprint_mismatch is False
    assert reset.index_reset is True
    with closing(reset._connect()) as con:
        assert con.execute("SELECT value FROM rag_meta WHERE key='index_fingerprint'").fetchone() == (current,)
        assert con.execute("SELECT value FROM rag_meta WHERE key='embedding_reset_version'").fetchone() == ("8.0",)


def test_indexed_paths_marks_vectorless_files_as_missing_after_embedding_reset(tmp_path: Path) -> None:
    from local_ai_hub.rag import RAGStore

    config = {
        "server": {"state_dir": str(tmp_path)},
        "models": {"embedding": "fixed-model", "embedding_backend": "sentence-transformers", "embedding_device": "cpu"},
        "cpu_retrieval": {},
        "rag": {},
        "workspace_cache": {},
        "resilience": {},
    }
    rag = RAGStore(config)
    with closing(rag._connect()) as con:
        con.execute("INSERT INTO files VALUES('w','a.py',1,14,'h')")
        con.execute("INSERT INTO chunks VALUES('w','a.py',0,'h','source','[]','')")
        con.commit()

    assert rag.indexed_paths(workspace="w", paths=["a.py"]) == set()


def test_v8_embedding_migration_is_release_gated() -> None:
    from tools.update_install import _release_requires_embedding_reset

    assert _release_requires_embedding_reset("7.9.9") is False
    assert _release_requires_embedding_reset("8.0.0") is True
    assert _release_requires_embedding_reset("8.0.1") is True
