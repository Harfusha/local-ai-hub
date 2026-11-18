from pathlib import Path
from unittest.mock import MagicMock
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
                root TEXT, path TEXT, content_hash TEXT, card_key TEXT
            );
            CREATE TABLE content_cards (
                content_hash TEXT, analyzer_version TEXT, card_key TEXT
            );
            CREATE TABLE source_index (
                root TEXT, path TEXT, content_hash TEXT, text TEXT, updated_at REAL,
                PRIMARY KEY (root, path)
            );
            CREATE TABLE source_fts (
                root TEXT, path TEXT, content TEXT, PRIMARY KEY (root, path)
            );
            """
        )
        con.execute(
            "INSERT INTO file_refs VALUES (?, ?, ?, NULL)",
            ("worktree_b", "src/example.py", "same-content"),
        )
        con.execute(
            "INSERT INTO source_index VALUES (?, ?, ?, ?, ?)",
            ("worktree_a", "src/example.py", "same-content", "def preserved(): pass", 1),
        )
        con.commit()

    preprocessor = object.__new__(ProjectPreprocessor)
    preprocessor.db_path = db_path
    preprocessor._sqlite_busy_seconds = 1
    preprocessor._db_lock = threading.RLock()

    preprocessor._link_content_reuse("worktree_b")

    with closing(sqlite3.connect(db_path)) as con:
        row = con.execute(
            "SELECT content FROM source_fts WHERE root=? AND path=?",
            ("worktree_b", "src/example.py"),
        ).fetchone()
    assert row == ("src/example.py\ndef preserved(): pass",)
