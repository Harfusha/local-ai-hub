import sqlite3
import threading
from contextlib import closing

import pytest

from local_ai_hub.preprocess import ProjectPreprocessor


def test_rag_pending_batch_does_not_enumerate_entire_inventory(tmp_path):
    db = tmp_path / "index.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE file_refs(root TEXT, path TEXT, content_hash TEXT, needs_hash INTEGER, rag_hash TEXT, last_accessed_at REAL, size INTEGER)")
        con.execute("INSERT INTO file_refs VALUES(?, 'pending.py', 'abc', 0, NULL, 0, 10)", (str(tmp_path),))
        con.commit()
    statements = []

    def connect():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        con.set_trace_callback(statements.append)
        return con

    class StopAfterSelection:
        def semantic_needed(self, root, path):
            raise RuntimeError("selected pending file")

    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._db_lock = threading.RLock()
    pre._connect = connect
    pre._yield = lambda: False
    pre.cfg = {"rag_files_per_step": 1}
    pre.deterministic = StopAfterSelection()

    with pytest.raises(RuntimeError, match="selected pending file"):
        pre._step_rag({"root": str(tmp_path), "workspace": "fixture"})

    assert not any("SELECT path FROM file_refs WHERE root=" in sql for sql in statements)


@pytest.mark.parametrize("change", ["content_hash='new'", "needs_hash=1"])
def test_rag_completion_does_not_mark_a_new_version_as_indexed(tmp_path, change):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "file.py").write_text("new", encoding="utf-8")
    db = tmp_path / "index.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE file_refs(root TEXT, path TEXT, content_hash TEXT, needs_hash INTEGER, rag_hash TEXT, last_accessed_at REAL, size INTEGER, updated_at REAL)")
        con.execute("CREATE TABLE source_index(root TEXT, path TEXT, content_hash TEXT, text TEXT)")
        con.execute("INSERT INTO file_refs VALUES(?, 'file.py', 'old', 0, NULL, 0, 3, 0)", (str(root),))
        con.execute("INSERT INTO source_index VALUES(?, 'file.py', 'old', 'old')", (str(root),))
        con.commit()

    def connect():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        return con

    class Rag:
        def index_paths_step(self, root, *, workspace, paths, should_yield, content_overrides):
            assert content_overrides == {"file.py": "old"}
            with closing(connect()) as con:
                con.execute(f"UPDATE file_refs SET {change} WHERE root=? AND path='file.py'", (root,))
                con.commit()
            return {"success": True, "processed_paths": paths}

    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._db_lock, pre._stats_lock = threading.RLock(), threading.RLock()
    pre._stats = {"rag_steps": 0}
    pre._connect, pre._yield = connect, lambda: False
    pre._record_progress = lambda *args: None
    pre.cfg, pre.deterministic, pre.rag = {"rag_files_per_step": 1}, None, Rag()
    assert pre._step_rag({"root": str(root), "workspace": "fixture"})
    with closing(connect()) as con:
        assert con.execute("SELECT rag_hash FROM file_refs").fetchone()[0] is None


def test_rag_does_not_use_source_text_from_an_older_version(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "file.py").write_text("new", encoding="utf-8")
    db = tmp_path / "index.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE file_refs(root TEXT, path TEXT, content_hash TEXT, needs_hash INTEGER, rag_hash TEXT, last_accessed_at REAL, size INTEGER, updated_at REAL)")
        con.execute("CREATE TABLE source_index(root TEXT, path TEXT, content_hash TEXT, text TEXT)")
        con.execute("INSERT INTO file_refs VALUES(?, 'file.py', 'new', 0, NULL, 0, 3, 0)", (str(root),))
        con.execute("INSERT INTO source_index VALUES(?, 'file.py', 'old', 'old')", (str(root),))
        con.commit()

    def connect():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        return con

    class Rag:
        def index_paths_step(self, root, *, workspace, paths, should_yield, content_overrides):
            assert content_overrides is None
            return {"preempted": True}

    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._db_lock, pre._stats_lock = threading.RLock(), threading.RLock()
    pre._stats = {"rag_steps": 0}
    pre._connect, pre._yield = connect, lambda: False
    pre.cfg, pre.deterministic, pre.rag = {"rag_files_per_step": 1}, None, Rag()
    assert pre._step_rag({"root": str(root), "workspace": "fixture"}) is False


@pytest.mark.parametrize("recreate", [True, False, "directory"])
def test_recreated_file_is_not_removed_by_old_rag_batch(tmp_path, recreate):
    root = tmp_path / "repo"
    root.mkdir()
    db = tmp_path / "index.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE file_refs(root TEXT, path TEXT, content_hash TEXT, needs_hash INTEGER, rag_hash TEXT, last_accessed_at REAL, size INTEGER, updated_at REAL)")
        con.execute("CREATE TABLE source_index(root TEXT, path TEXT, content_hash TEXT, text TEXT)")
        con.execute("CREATE VIRTUAL TABLE source_fts USING fts5(root UNINDEXED,path UNINDEXED,content)")
        con.execute("INSERT INTO file_refs VALUES(?, 'file.py', 'old', 0, NULL, 0, 3, 0)", (str(root),))
        con.execute("INSERT INTO source_index VALUES(?, 'file.py', 'old', 'old')", (str(root),))
        con.execute("INSERT INTO source_fts VALUES(?, 'file.py', 'old')", (str(root),))
        con.commit()

    def connect():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        return con

    class Rag:
        def index_paths_step(self, *args, **kwargs):
            return {"success": True, "processed_paths": []}

        def remove_paths(self, **kwargs):
            if recreate == "directory":
                (root / "file.py").mkdir()
            elif recreate:
                (root / "file.py").write_text("new", encoding="utf-8")
                with closing(connect()) as con:
                    con.execute("UPDATE file_refs SET content_hash='new', needs_hash=0 WHERE root=?", (str(root),))
                    con.commit()

    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._db_lock, pre._stats_lock = threading.RLock(), threading.RLock()
    pre._stats = {"rag_steps": 0}
    pre._connect, pre._yield = connect, lambda: False
    pre._record_progress = lambda *args: None
    pre.cfg, pre.deterministic, pre.rag = {"rag_files_per_step": 1}, None, Rag()
    assert pre._step_rag({"root": str(root), "workspace": "fixture"})
    with closing(connect()) as con:
        row = con.execute("SELECT content_hash,needs_hash,rag_hash FROM file_refs").fetchone()
        if recreate is True:
            assert tuple(row) == ("new", 1, None)
            assert con.execute("SELECT COUNT(*) FROM source_index").fetchone()[0] == 1
        else:
            assert row is None
            assert con.execute("SELECT COUNT(*) FROM source_index").fetchone()[0] == 0
