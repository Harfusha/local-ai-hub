from pathlib import Path
from unittest.mock import MagicMock
import pytest
from local_ai_hub.rag import RAGStore


def test_rag_chunks_reused_across_workspaces_without_embedding_calls(tmp_path: Path):
    cfg = {"server": {"state_dir": str(tmp_path / "state")}}
    services = MagicMock()
    # Mock embed return
    services.embed.return_value = {
        "success": True,
        "embeddings": [[0.1] * 384],
    }

    rag = RAGStore(cfg, services)

    ws_a = "workspace_a"
    ws_b = "workspace_b"
    file_a = tmp_path / "a/file.py"
    file_b = tmp_path / "b/file.py"
    file_a.parent.mkdir(parents=True)
    file_b.parent.mkdir(parents=True)
    file_a.write_text("def hello(): return 123\n", encoding="utf-8")
    file_b.write_text("def hello(): return 123\n", encoding="utf-8")

    # Index in workspace A
    res_a = rag.index_paths_step(str(file_a.parent), workspace=ws_a, paths=["file.py"])
    assert res_a.get("success") is True
    assert res_a.get("embedded_chunks") == 1
    assert res_a.get("reused_chunks") == 0
    assert services.embed.call_count == 1

    # Now index in workspace B with identical content
    res_b = rag.index_paths_step(str(file_b.parent), workspace=ws_b, paths=["file.py"])
    assert res_b.get("success") is True
    # Should reuse chunks from workspace A via CAS matching content_hash
    assert res_b.get("embedded_chunks") == 0
    assert res_b.get("reused_chunks") == 1
    # embed should NOT have been called a second time!
    assert services.embed.call_count == 1


def test_preprocessor_links_lexical_source_text_across_worktrees(tmp_path: Path):
    import sqlite3
    import threading
    from contextlib import closing

    from local_ai_hub.preprocess import ProjectPreprocessor

    db_path = tmp_path / "preprocess.sqlite3"
    with closing(sqlite3.connect(db_path)) as con:
        con.executescript(
            """
            CREATE TABLE file_refs (
                root TEXT, path TEXT, content_hash TEXT, card_key TEXT, needs_hash INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE content_cards (
                content_hash TEXT, analyzer_version TEXT, card_key TEXT, model TEXT, card_json TEXT, hits INTEGER
            );
            CREATE TABLE source_index (
                root TEXT, path TEXT, content_hash TEXT, text TEXT, updated_at REAL,
                text_origin TEXT NOT NULL DEFAULT 'unknown',
                PRIMARY KEY (root, path)
            );
            CREATE TABLE content_lexical (content_hash TEXT PRIMARY KEY, text TEXT, updated_at REAL);
            CREATE VIRTUAL TABLE source_fts USING fts5(root UNINDEXED, path UNINDEXED, content);
            """
        )
        con.execute(
            "INSERT INTO file_refs(root,path,content_hash,card_key) VALUES (?, ?, ?, NULL)",
            ("worktree_b", "src/example.py", "same-content"),
        )
        con.executemany(
            "INSERT INTO source_index VALUES (?, ?, ?, ?, 1, ?)",
            [
                ("projection", "src/example.py", "same-content", "foreign_projection", "projection"),
                ("worktree_a", "src/example.py", "same-content", "def preserved(): pass", "source"),
                ("projection", "src/projected.py", "projection-only", "foreign_projection", "projection"),
                ("legacy", "src/legacy.py", "legacy-content", "legacy_projection", "unknown"),
            ],
        )
        con.executemany(
            "INSERT INTO file_refs(root,path,content_hash,needs_hash) VALUES (?,?,?,?)",
            [
                ("worktree_b", "src/pending.py", "same-content", 1),
                ("worktree_b", "src/changed.py", "new-content", 0),
                ("worktree_b", "src/watcher.py", "watcher-content", 1),
                ("worktree_b", "src/projected.py", "projection-only", 0),
                ("worktree_b", "src/legacy.py", "legacy-content", 0),
            ],
        )
        con.executemany(
            "INSERT INTO source_index(root,path,content_hash,text,updated_at) VALUES (?,?,?,?,1)",
            [
                ("worktree_b", "src/changed.py", "previous-content", "stale_change"),
                ("worktree_b", "src/watcher.py", "watcher-content", "stale_watcher"),
                ("worktree_b", "src/deleted.py", "deleted-content", "stale_removed"),
            ],
        )
        con.commit()

    preprocessor = object.__new__(ProjectPreprocessor)
    preprocessor.db_path = db_path
    preprocessor._sqlite_busy_seconds = 1
    preprocessor._db_lock = threading.RLock()

    preprocessor._link_content_reuse("worktree_b")

    with closing(sqlite3.connect(db_path)) as con:
        rows = con.execute(
            "SELECT path FROM source_fts WHERE root=? AND source_fts MATCH ?",
            ("worktree_b", "preserved OR stale"),
        ).fetchall()
        linked = con.execute(
            "SELECT path, text_origin FROM source_index WHERE root=? AND path IN (?,?,?,?)",
            ("worktree_b", "src/example.py", "src/pending.py", "src/projected.py", "src/legacy.py"),
        ).fetchall()
    assert rows == [("src/example.py",)]
    assert linked == [("src/example.py", "source")]


def test_lexical_text_survives_original_worktree_purge(tmp_path: Path, monkeypatch):
    from contextlib import closing
    from types import SimpleNamespace

    from local_ai_hub.preprocess import ProjectPreprocessor
    from local_ai_hub.repo_tools import RepositoryTools

    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": False},
        "rag": {"extensions": [".py"]},
    }
    scheduler = SimpleNamespace(background_allowed=lambda: True, foreground_busy=lambda: False, status=lambda: {})
    root_a, root_b = tmp_path / "worktree-a", tmp_path / "worktree-b"
    root_a.mkdir()
    root_b.mkdir()
    content = "portablelexicalneedle = 42\n"
    (root_a / "original.py").write_text(content, encoding="utf-8")
    (root_b / "renamed.py").write_text(content, encoding="utf-8")

    def open_preprocessor():
        pre = ProjectPreprocessor(config, None, RAGStore(config, None), scheduler, None, RepositoryTools(config))
        monkeypatch.setattr(pre, "enabled", True)
        return pre

    def inventory_and_hash(pre, root):
        pre.register(str(root))
        row = dict(pre._project_row(str(root)))
        assert pre._step_inventory(row) is True
        assert pre._step_hash(dict(pre._project_row(str(root)))) is True

    first = open_preprocessor()
    try:
        inventory_and_hash(first, root_a)
        assert first._step_lexical({"root": str(root_a)}) is True
        assert first.candidate_paths_lexical(str(root_a), "portablelexicalneedle") == ["original.py"]
        assert first.unregister(str(root_a), purge_data=True)["purged"] is True
        with closing(first._connect()) as con:
            assert con.execute("SELECT COUNT(*) FROM source_index").fetchone()[0] == 0
    finally:
        first.close()

    second = open_preprocessor()
    try:
        inventory_and_hash(second, root_b)
        lexical_ingests = []
        get_or_ingest = second.ingest_cache.get_or_ingest

        def observe_ingest(*args, **kwargs):
            lexical_ingests.append(args[1])
            return get_or_ingest(*args, **kwargs)

        monkeypatch.setattr(second.ingest_cache, "get_or_ingest", observe_ingest)
        assert second._step_lexical({"root": str(root_b)}) is True
        assert second.candidate_paths_lexical(str(root_b), "portablelexicalneedle") == ["renamed.py"]
        assert lexical_ingests == []
    finally:
        second.close()


def test_runtime_refuses_legacy_lexical_schema_until_update_migration(tmp_path: Path):
    import sqlite3
    import threading
    from contextlib import closing

    from local_ai_hub.preprocess import ProjectPreprocessor

    preprocessor = object.__new__(ProjectPreprocessor)
    preprocessor.db_path = tmp_path / "preprocess.sqlite3"
    preprocessor._sqlite_busy_seconds = 1
    preprocessor._db_lock = threading.RLock()
    with closing(sqlite3.connect(preprocessor.db_path)) as con:
        con.executescript(
            """
            CREATE TABLE source_index (
                root TEXT NOT NULL, path TEXT NOT NULL, content_hash TEXT NOT NULL,
                text TEXT NOT NULL, updated_at REAL NOT NULL, PRIMARY KEY (root, path)
            );
            CREATE VIRTUAL TABLE source_fts USING fts5(root UNINDEXED, path UNINDEXED, content);
            INSERT INTO source_index VALUES ('worktree_a', 'src/example.py', 'hash', 'legacytext', 1);
            INSERT INTO source_fts VALUES ('worktree_a', 'src/example.py', 'legacytext');
            """
        )

    with pytest.raises(sqlite3.DatabaseError, match="update-time lexical-index migration"):
        preprocessor._init_db()

    with closing(sqlite3.connect(preprocessor.db_path)) as con:
        assert con.execute("SELECT content_hash,text FROM source_index").fetchall() == [
            ("hash", "legacytext"),
        ]
        assert con.execute("SELECT root,path FROM source_fts WHERE source_fts MATCH 'legacytext'").fetchall() == [
            ("worktree_a", "src/example.py"),
        ]
