import sqlite3
import threading
from contextlib import closing

import pytest

from local_ai_hub.preprocess import ProjectPreprocessor


def test_rag_pending_batch_does_not_enumerate_entire_inventory(tmp_path):
    db = tmp_path / "index.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE file_refs(root TEXT, path TEXT, content_hash TEXT, needs_hash INTEGER, rag_hash TEXT, last_accessed_at REAL, size INTEGER, centrality_score REAL NOT NULL DEFAULT 0.0)")
        con.execute("INSERT INTO file_refs(root,path,content_hash,needs_hash,rag_hash,last_accessed_at,size) VALUES(?, 'pending.py', 'abc', 0, NULL, 0, 10)", (str(tmp_path),))
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
    pre.rag = type("EmptyRag", (), {"paths_needing_reindex": lambda *_args, **_kwargs: []})()
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
        con.execute("CREATE TABLE file_refs(root TEXT, path TEXT, content_hash TEXT, needs_hash INTEGER, rag_hash TEXT, last_accessed_at REAL, size INTEGER, updated_at REAL, centrality_score REAL NOT NULL DEFAULT 0.0)")
        con.execute("CREATE TABLE source_index(root TEXT, path TEXT, content_hash TEXT, text TEXT)")
        con.execute("INSERT INTO file_refs(root,path,content_hash,needs_hash,rag_hash,last_accessed_at,size,updated_at) VALUES(?, 'file.py', 'old', 0, NULL, 0, 3, 0)", (str(root),))
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


@pytest.mark.parametrize("donor_origin", ["source", "projection", "unknown"])
def test_rag_uses_current_text_and_only_reuses_source_text_from_other_roots(tmp_path, donor_origin):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "file.py").write_text("new", encoding="utf-8")
    db = tmp_path / "index.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE file_refs(root TEXT, path TEXT, content_hash TEXT, needs_hash INTEGER, rag_hash TEXT, last_accessed_at REAL, size INTEGER, updated_at REAL, centrality_score REAL NOT NULL DEFAULT 0.0)")
        con.execute("CREATE TABLE source_index(root TEXT, path TEXT, content_hash TEXT, text TEXT, text_origin TEXT)")
        con.execute("INSERT INTO file_refs(root,path,content_hash,needs_hash,rag_hash,last_accessed_at,size,updated_at) VALUES(?, 'file.py', 'new', 0, NULL, 0, 3, 0)", (str(root),))
        con.execute("INSERT INTO source_index VALUES(?, 'file.py', 'old', 'old', 'source')", (str(root),))
        con.execute("INSERT INTO source_index VALUES('donor', 'file.py', 'new', 'new', ?)", (donor_origin,))
        con.commit()

    def connect():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        return con

    class Rag:
        def index_paths_step(self, root, *, workspace, paths, should_yield, content_overrides):
            expected = {"file.py": "new"} if donor_origin == "source" else None
            assert content_overrides == expected
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
        con.execute("CREATE TABLE file_refs(root TEXT, path TEXT, content_hash TEXT, needs_hash INTEGER, rag_hash TEXT, last_accessed_at REAL, size INTEGER, updated_at REAL, centrality_score REAL NOT NULL DEFAULT 0.0)")
        con.execute("CREATE TABLE source_index(root TEXT, path TEXT, content_hash TEXT, text TEXT)")
        con.execute("CREATE VIRTUAL TABLE source_fts USING fts5(root UNINDEXED,path UNINDEXED,content)")
        con.execute("INSERT INTO file_refs(root,path,content_hash,needs_hash,rag_hash,last_accessed_at,size,updated_at) VALUES(?, 'file.py', 'old', 0, NULL, 0, 3, 0)", (str(root),))
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


def test_checked_relative_source_classifications(tmp_path):
    from local_ai_hub.preprocess import checked_relative_source

    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    (root / "regular.py").write_text("code", encoding="utf-8")
    (root / "subdir").mkdir()

    # Regular file
    assert checked_relative_source(root, "regular.py") == "inside_regular_file"
    # Missing file
    assert checked_relative_source(root, "nonexistent.py") == "missing"
    # Directory
    assert checked_relative_source(root, "subdir") == "directory"
    # Rooted / parent escapes
    assert checked_relative_source(root, "../outside/secret.txt") == "escaped"
    assert checked_relative_source(root, str(outside / "secret.txt")) == "escaped"

    # Symlink pointing outside root
    symlink_out = root / "symlink_out.py"
    try:
        symlink_out.symlink_to(outside / "secret.txt")
        assert checked_relative_source(root, "symlink_out.py") == "escaped"
    except OSError:
        pass


def test_rag_cleanup_escaped_path_removes_ref_safely(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("secret", encoding="utf-8")

    db = tmp_path / "index.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE file_refs(root TEXT, path TEXT, content_hash TEXT, needs_hash INTEGER, rag_hash TEXT, last_accessed_at REAL, size INTEGER, updated_at REAL, centrality_score REAL NOT NULL DEFAULT 0.0)")
        con.execute("CREATE TABLE source_index(root TEXT, path TEXT, content_hash TEXT, text TEXT)")
        con.execute("CREATE VIRTUAL TABLE source_fts USING fts5(root UNINDEXED,path UNINDEXED,content)")
        con.execute("INSERT INTO file_refs(root,path,content_hash,needs_hash,rag_hash,last_accessed_at,size,updated_at) VALUES(?, 'escaped.py', 'old', 0, NULL, 0, 3, 0)", (str(root),))
        con.execute("INSERT INTO source_index VALUES(?, 'escaped.py', 'old', 'old')", (str(root),))
        con.execute("INSERT INTO source_fts VALUES(?, 'escaped.py', 'old')", (str(root),))
        con.commit()

    symlink_escaped = root / "escaped.py"
    try:
        symlink_escaped.symlink_to(secret)
    except OSError:
        pass

    def connect():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        return con

    class Rag:
        def index_paths_step(self, *args, **kwargs):
            return {"success": True, "processed_paths": []}

        def remove_paths(self, **kwargs):
            pass

    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._db_lock, pre._stats_lock = threading.RLock(), threading.RLock()
    pre._stats = {"rag_steps": 0}
    pre._connect, pre._yield = connect, lambda: False
    pre._record_progress = lambda *args: None
    pre.cfg, pre.deterministic, pre.rag = {"rag_files_per_step": 1}, None, Rag()
    assert pre._step_rag({"root": str(root), "workspace": "fixture"})
    with closing(connect()) as con:
        assert con.execute("SELECT COUNT(*) FROM file_refs").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM source_index").fetchone()[0] == 0


def test_rag_idle_skips_full_inventory_scan_when_digest_matches(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    db = tmp_path / "index.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE file_refs(root TEXT, path TEXT, content_hash TEXT, needs_hash INTEGER, rag_hash TEXT, last_accessed_at REAL, size INTEGER, updated_at REAL, centrality_score REAL NOT NULL DEFAULT 0.0)")
        con.execute("CREATE TABLE file_refs_revision(root TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0)")
        con.execute("CREATE TABLE projects(root TEXT, phase TEXT, status TEXT, updated_at REAL)")
        con.execute("INSERT INTO file_refs(root,path,content_hash,needs_hash,rag_hash,last_accessed_at,size,updated_at) VALUES(?, 'a.py', 'h1', 0, 'h1', 0, 10, 0)", (str(root),))
        con.execute("INSERT INTO file_refs_revision VALUES(?, 1)", (str(root),))
        con.execute("INSERT INTO projects VALUES(?, 'rag', 'running', 0)", (str(root),))
        con.commit()

    prune_calls = []

    class MockRag:
        def indexed_paths(self, workspace, paths):
            return set(paths)

        def prune_missing(self, root, workspace, all_paths):
            prune_calls.append(len(all_paths))
            return 0

    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._db_lock = threading.RLock()
    pre._stats_lock = threading.RLock()
    pre._stats = {}
    pre._rag_inventory_digests = {}
    pre._connect = lambda: sqlite3.connect(db)
    pre._yield = lambda: False
    pre.cfg = {"rag_idle_audit_cadence_seconds": 300.0}
    pre.deterministic = None
    pre.rag = MockRag()
    pre._set_project = lambda r, **kwargs: None

    # First call: no pending files, runs full audit and records digest
    assert pre._step_rag({"root": str(root), "workspace": "ws"})
    assert len(prune_calls) == 1
    assert prune_calls[0] == 1

    # Second call: digest unchanged, cadence fresh -> skips full audit/prune
    assert pre._step_rag({"root": str(root), "workspace": "ws"})
    assert len(prune_calls) == 1  # No additional prune call

    # Third call: bump revision -> full audit triggers
    with closing(sqlite3.connect(db)) as con:
        con.execute("UPDATE file_refs_revision SET revision=2 WHERE root=?", (str(root),))
        con.commit()
    assert pre._step_rag({"root": str(root), "workspace": "ws"})
    assert len(prune_calls) == 2

    # Fourth call: force_refresh -> full audit triggers
    assert pre._step_rag({"root": str(root), "workspace": "ws", "force_refresh": 1})
    assert len(prune_calls) == 3



def test_rag_idle_detects_lost_chunk_inventory_inside_audit_cadence(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    db = tmp_path / "index.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE file_refs(root TEXT, path TEXT, content_hash TEXT, needs_hash INTEGER, rag_hash TEXT, last_accessed_at REAL, size INTEGER, updated_at REAL, centrality_score REAL)")
        con.execute("CREATE TABLE file_refs_revision(root TEXT PRIMARY KEY, revision INTEGER)")
        con.execute("INSERT INTO file_refs VALUES(?, 'a.py', 'h1', 0, 'h1', 0, 10, 0, 0)", (str(root),))
        con.execute("INSERT INTO file_refs_revision VALUES(?, 1)", (str(root),))
        con.commit()

    class Rag:
        def __init__(self):
            self.chunks = 2
            self.prune_calls = 0

        def workspace_stats(self, workspaces):
            return {workspaces[0]: {"files": 1 if self.chunks else 0, "chunks": self.chunks,
                                    "chunked_files": 1 if self.chunks else 0}}

        def indexed_paths(self, *, workspace, paths):
            return set(paths) if self.chunks else set()

        def prune_missing(self, root, workspace, all_paths):
            self.prune_calls += 1
            return 0

    rag = Rag()
    prep = ProjectPreprocessor.__new__(ProjectPreprocessor)
    prep._db_lock = threading.RLock()
    prep._stats_lock = threading.RLock()
    prep._stats = {}
    prep._rag_inventory_digests = {}
    prep._connect = lambda: sqlite3.connect(db)
    prep._yield = lambda: False
    prep.cfg = {"rag_idle_audit_cadence_seconds": 300.0}
    prep.deterministic = None
    prep.rag = rag
    prep._set_project = lambda *args, **kwargs: None
    assert prep._step_rag({"root": str(root), "workspace": "ws"})
    assert rag.prune_calls == 1
    assert prep._step_rag({"root": str(root), "workspace": "ws"})
    assert rag.prune_calls == 1
    rag.chunks = 0
    assert prep._step_rag({"root": str(root), "workspace": "ws"})
    assert rag.prune_calls == 1  # Missing index triggers rag_hash invalidation instead of false DONE.
    with closing(sqlite3.connect(db)) as con:
        assert con.execute("SELECT rag_hash FROM file_refs").fetchone()[0] is None


def test_rag_marks_policy_excluded_paths_complete_to_avoid_retry_loop(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "excluded.py").write_text("excluded", encoding="utf-8")
    db = tmp_path / "index.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute(
            "CREATE TABLE file_refs(root TEXT, path TEXT, content_hash TEXT, needs_hash INTEGER, "
            "rag_hash TEXT, last_accessed_at REAL, size INTEGER, updated_at REAL, centrality_score REAL NOT NULL DEFAULT 0.0)"
        )
        con.execute("CREATE TABLE source_index(root TEXT, path TEXT, content_hash TEXT, text TEXT, text_origin TEXT)")
        con.execute(
            "INSERT INTO file_refs(root,path,content_hash,needs_hash,rag_hash,last_accessed_at,size,updated_at) VALUES(?, 'excluded.py', 'hash', 0, NULL, 0, 8, 0)",
            (str(root),),
        )
        con.commit()

    def connect():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        return con

    class Rag:
        def index_paths_step(self, _root, *, workspace, paths, **_kwargs):
            return {"success": True, "processed_paths": [], "policy_deleted_paths": paths}

    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._db_lock, pre._stats_lock = threading.RLock(), threading.RLock()
    pre._stats = {"rag_steps": 0}
    pre._connect, pre._yield = connect, lambda: False
    pre._record_progress = lambda *_args: None
    pre.cfg, pre.deterministic, pre.rag = {"rag_files_per_step": 1}, None, Rag()

    assert pre._step_rag({"root": str(root), "workspace": "fixture"})
    with closing(connect()) as con:
        assert con.execute("SELECT rag_hash FROM file_refs").fetchone()[0] == "hash"
