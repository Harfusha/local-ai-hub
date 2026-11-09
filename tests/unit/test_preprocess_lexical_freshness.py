import sqlite3
import threading
import hashlib
from contextlib import closing

import pytest

from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.repo_tools import RepositoryTools


@pytest.mark.parametrize("race", ["read_new_bytes", "watcher_update", "unchanged"])
def test_lexical_index_does_not_publish_stale_identity(tmp_path, race):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("new content", encoding="utf-8")
    db = tmp_path / "state.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE file_refs(root TEXT,path TEXT,content_hash TEXT,needs_hash INTEGER)")
        con.execute("CREATE TABLE source_index(root TEXT,path TEXT,content_hash TEXT,text TEXT,updated_at REAL,PRIMARY KEY(root,path))")
        con.execute("CREATE VIRTUAL TABLE source_fts USING fts5(root UNINDEXED,path UNINDEXED,content)")
        con.execute("INSERT INTO file_refs VALUES(?, 'a.py', 'old', 0)", (str(root),))
        con.commit()

    def connect():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        return con

    class Repo:
        def _read_snapshot(self, path):
            if race == "watcher_update":
                with closing(connect()) as con:
                    con.execute("UPDATE file_refs SET content_hash='new' WHERE root=?", (str(root),))
                    con.commit()
                return "old", ["old content"]
            if race == "read_new_bytes":
                return "new", ["new content"]
            return "old", ["old content"]

    class Pool:
        def map(self, fn, values):
            return map(fn, values)

    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._connect, pre._db_lock = connect, threading.RLock()
    pre._stats_lock, pre._stats = threading.RLock(), {}
    pre._find_lexical_pending = lambda root, limit: [{"path": "a.py", "content_hash": "old"}]
    pre._record_progress = lambda *args: None
    pre.repo_tools, pre._cpu_pool, pre.deterministic, pre.cfg = Repo(), Pool(), None, {}
    assert pre._step_lexical({"root": str(root)})
    with closing(connect()) as con:
        expected = 1 if race == "unchanged" else 0
        assert con.execute("SELECT COUNT(*) FROM source_index").fetchone()[0] == expected
        assert con.execute("SELECT COUNT(*) FROM source_fts").fetchone()[0] == expected
        if race == "read_new_bytes":
            assert con.execute("SELECT needs_hash FROM file_refs").fetchone()[0] == 1


@pytest.mark.parametrize("changed", [False, True])
def test_lexical_requeues_legacy_git_identities_for_sha256(tmp_path, changed):
    root = tmp_path / "repo"
    root.mkdir()
    original = b"line one\r\nline two\r\n"
    path = root / "a.py"
    path.write_bytes(b"changed" if changed else original)
    identity = "git:" + hashlib.sha1(b"blob " + str(len(original)).encode() + b"\0" + original).hexdigest()
    db = tmp_path / "state.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE file_refs(root TEXT,path TEXT,content_hash TEXT,needs_hash INTEGER)")
        con.execute("CREATE TABLE source_index(root TEXT,path TEXT,content_hash TEXT,text TEXT,updated_at REAL,PRIMARY KEY(root,path))")
        con.execute("CREATE VIRTUAL TABLE source_fts USING fts5(root UNINDEXED,path UNINDEXED,content)")
        con.execute("INSERT INTO file_refs VALUES(?, 'a.py', ?, 0)", (str(root), identity))
        con.commit()
    def connect():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        return con
    class Pool:
        def map(self, fn, values):
            return map(fn, values)
    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._connect, pre._db_lock = connect, threading.RLock()
    pre._stats_lock, pre._stats = threading.RLock(), {}
    pre._find_lexical_pending = lambda root, limit: [{"path": "a.py", "content_hash": identity}]
    pre._record_progress = lambda *args: None
    pre.repo_tools, pre._cpu_pool, pre.deterministic, pre.cfg = RepositoryTools({}), Pool(), None, {}
    assert pre._step_lexical({"root": str(root)})
    with closing(connect()) as con:
        assert con.execute("SELECT COUNT(*) FROM source_index").fetchone()[0] == 0
        assert con.execute("SELECT needs_hash FROM file_refs").fetchone()[0] == 1
