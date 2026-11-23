import sqlite3
import threading
import hashlib
from contextlib import closing, contextmanager
from types import SimpleNamespace

import pytest

from local_ai_hub import preprocess as preprocess_module
from local_ai_hub.preprocess import ProjectPreprocessor, _ensure_file_refs_revision_tracking
from local_ai_hub.repo_tools import RepositoryTools


@pytest.mark.parametrize("race", ["read_new_bytes", "watcher_update", "unchanged", "projection"])
def test_lexical_index_does_not_publish_stale_identity(tmp_path, race):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("new content", encoding="utf-8")
    db = tmp_path / "state.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE file_refs(root TEXT,path TEXT,content_hash TEXT,needs_hash INTEGER)")
        con.execute("CREATE TABLE source_index(root TEXT,path TEXT,content_hash TEXT,text TEXT,updated_at REAL,text_origin TEXT,PRIMARY KEY(root,path))")
        con.execute("CREATE TABLE content_lexical(content_hash TEXT PRIMARY KEY,text TEXT,updated_at REAL)")
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

    class Deterministic:
        def lexical_projection(self, root, path, max_chars):
            return "root-specific facts"

    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._connect, pre._db_lock = connect, threading.RLock()
    pre._stats_lock, pre._stats = threading.RLock(), {}
    pre._find_lexical_pending = lambda root, limit: [{"path": "a.py", "content_hash": "old"}]
    pre._record_progress = lambda *args: None
    pre.repo_tools, pre._cpu_pool, pre.deterministic, pre.cfg = Repo(), Pool(), None, {}
    if race == "projection":
        pre.deterministic = Deterministic()
    assert pre._step_lexical({"root": str(root)})
    with closing(connect()) as con:
        expected = {"unchanged": [("old content", "source")], "projection": [("root-specific facts", "projection")]}.get(race, [])
        assert [tuple(row) for row in con.execute("SELECT text,text_origin FROM source_index")] == expected
        expected_cas = [("old", "old content")] if race == "unchanged" else []
        assert [tuple(row) for row in con.execute("SELECT content_hash,text FROM content_lexical")] == expected_cas
        assert con.execute("SELECT COUNT(*) FROM source_fts").fetchone()[0] == len(expected)
        if race == "read_new_bytes":
            assert con.execute("SELECT needs_hash FROM file_refs").fetchone()[0] == 1


def test_ranked_lexical_readers_filter_stale_paths_before_the_limit(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    db = tmp_path / "preprocess.sqlite3"
    entries = {
        "dirty.py": ("needle", "old", "old", 1),
        "changed.py": ("needle", "old", "new", 0),
        "orphan.py": ("needle", "old", None, 0),
        "good.py": ("needle other content", "good", "good", 0),
        "long.py": ("needle " + "other " * 20, "long", "long", 0),
        "needle_by_path.py": ("ordinary source content", "path", "path", 0),
    }
    wanted = ("good.py", "long.py", "needle_by_path.py")
    root_key = str(root.resolve())
    with closing(sqlite3.connect(db)) as con:
        con.executescript("""
            CREATE TABLE file_refs(root TEXT,path TEXT,content_hash TEXT,needs_hash INTEGER,PRIMARY KEY(root,path));
            CREATE TABLE source_index(root TEXT,path TEXT,content_hash TEXT,text TEXT,PRIMARY KEY(root,path));
            CREATE VIRTUAL TABLE source_fts USING fts5(root UNINDEXED,path UNINDEXED,content);
        """)
        _ensure_file_refs_revision_tracking(con)
        for path, (text, indexed_hash, current_hash, needs_hash) in entries.items():
            (root / path).write_text(text, encoding="utf-8")
            if current_hash is not None:
                con.execute("INSERT INTO file_refs VALUES(?,?,?,?)", (root_key, path, current_hash, needs_hash))
            con.execute("INSERT INTO source_index VALUES(?,?,?,?)", (root_key, path, indexed_hash, text))
            con.execute("INSERT INTO source_fts VALUES(?,?,?)", (root_key, path, path + "\n" + text))
        con.execute("INSERT INTO source_fts VALUES(?,?,?)", (root_key + "-another", "foreign.py", "needle"))
        order = "SELECT path FROM source_fts WHERE root=? AND source_fts MATCH 'needle'"
        raw = tuple(row[0] for row in con.execute(order + " ORDER BY bm25(source_fts),rowid LIMIT 3", (root_key,)))
        expected = tuple(row[0] for row in con.execute(
            order + " AND path IN (?,?,?) ORDER BY bm25(source_fts),rowid", (root_key, *wanted),
        ))
        assert set(expected) == set(wanted)
        assert raw != expected
        con.commit()

    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._connect = lambda: sqlite3.connect(db)
    pre._db_lock = threading.RLock()
    pre.repo_tools = RepositoryTools({})
    pre.state_dir = tmp_path / "state"
    pre._project_settings = lambda _root: {}
    pre._project_path_allowed = lambda *_args, **_kwargs: True
    pre.learner = SimpleNamespace(hot_queries=lambda *_args: ["needle"])
    pre._demand_priority_cache, pre._demand_priority_lock = {}, threading.Lock()

    assert pre.candidate_paths_lexical(root_key, "needle", limit=3) == list(expected)
    assert pre._learned_priority_paths(root_key) == expected
    with closing(sqlite3.connect(db)) as con:
        con.execute("UPDATE file_refs SET needs_hash=1 WHERE root=? AND path=?", (root_key, expected[0]))
        con.commit()
    assert pre._learned_priority_paths(root_key) == expected[1:]
    assert pre.candidate_paths_lexical(root_key, "needle", limit=3) == list(expected[1:])


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


def test_lexical_index_writes_bounded_fts_batches(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("alpha", encoding="utf-8")
    (root / "b.py").write_text("beta", encoding="utf-8")
    db = tmp_path / "state.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE file_refs(root TEXT,path TEXT,content_hash TEXT,needs_hash INTEGER)")
        con.execute("CREATE TABLE source_index(root TEXT,path TEXT,content_hash TEXT,text TEXT,updated_at REAL,text_origin TEXT,PRIMARY KEY(root,path))")
        con.execute("CREATE TABLE content_lexical(content_hash TEXT PRIMARY KEY,text TEXT,updated_at REAL)")
        con.execute("CREATE VIRTUAL TABLE source_fts USING fts5(root UNINDEXED,path UNINDEXED,content)")
        con.executemany(
            "INSERT INTO file_refs VALUES(?, ?, ?, 0)",
            [(str(root), "a.py", "hash-a"), (str(root), "b.py", "hash-b")],
        )
        con.commit()

    def connect():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        return con

    class Repo:
        def _read_snapshot(self, path):
            rel = path.name
            return ("hash-a", ["alpha"]) if rel == "a.py" else ("hash-b", ["beta"])

    class Pool:
        def map(self, fn, values):
            return map(fn, values)

    original_transaction = preprocess_module.write_transaction
    transaction_count = 0

    @contextmanager
    def counted_transaction(*args, **kwargs):
        nonlocal transaction_count
        transaction_count += 1
        with original_transaction(*args, **kwargs) as transaction:
            yield transaction

    monkeypatch.setattr(preprocess_module, "_LEXICAL_WRITE_BATCH_SIZE", 1)
    monkeypatch.setattr(preprocess_module, "write_transaction", counted_transaction)
    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._connect, pre._db_lock = connect, threading.RLock()
    pre._stats_lock, pre._stats = threading.RLock(), {}
    pre._find_lexical_pending = lambda root, limit: [
        {"path": "a.py", "content_hash": "hash-a"},
        {"path": "b.py", "content_hash": "hash-b"},
    ]
    pre._record_progress = lambda *args: None
    pre.repo_tools, pre._cpu_pool, pre.deterministic, pre.cfg = Repo(), Pool(), None, {}

    assert pre._step_lexical({"root": str(root)})
    assert transaction_count == 2
    with closing(connect()) as con:
        assert con.execute("SELECT COUNT(*) FROM source_index").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM source_fts").fetchone()[0] == 2
        assert {row[0] for row in con.execute("SELECT path FROM source_fts")} == {"a.py", "b.py"}
