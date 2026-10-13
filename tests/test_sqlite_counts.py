from contextlib import closing
import sqlite3
import threading

import pytest

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.sqlite_counts import global_row_counts, initialize_row_counts


def test_counts_preserve_replacement_ignore_rollback_and_delete(tmp_path):
    with closing(sqlite3.connect(tmp_path / "counts.sqlite")) as con:
        con.execute("CREATE TABLE files(id INTEGER PRIMARY KEY, name TEXT UNIQUE)")
        con.executemany("INSERT INTO files VALUES(?,?)", [(1, "a"), (2, "b")])
        con.commit()
        initialize_row_counts(con, ("files",))
        assert global_row_counts(con, ("files",)) == {"files": 2}
        con.execute("INSERT OR REPLACE INTO files VALUES(1,'b')")  # replaces two rows
        con.execute("INSERT OR IGNORE INTO files VALUES(3,'b')")
        con.execute("INSERT INTO files VALUES(1,'c') ON CONFLICT(id) DO UPDATE SET name=excluded.name")
        con.commit()
        assert global_row_counts(con, ("files",)) == {"files": 1}
        con.execute("INSERT INTO files VALUES(4,'d')")
        con.execute("DELETE FROM files WHERE id=1")
        con.rollback()
        assert global_row_counts(con, ("files",)) == {"files": 1}
        initialize_row_counts(con, ("files",))
        assert global_row_counts(con, ("files",)) == {"files": 1}
        con.execute("DELETE FROM files")
        assert global_row_counts(con, ("files",)) == {"files": 0}


def test_count_initialization_does_not_commit_callers_transaction(tmp_path):
    with closing(sqlite3.connect(tmp_path / "counts.sqlite")) as con:
        con.execute("CREATE TABLE files(id INTEGER PRIMARY KEY)")
        con.execute("INSERT INTO files VALUES(1)")
        initialize_row_counts(con, ("files",))
        con.rollback()
        assert con.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
        assert con.execute("SELECT name FROM sqlite_master WHERE name='hub_row_counts'").fetchone() is None


def test_count_initialization_failure_rolls_back_partial_schema(tmp_path):
    with closing(sqlite3.connect(tmp_path / "counts.sqlite")) as con:
        con.execute("CREATE TABLE files(id INTEGER PRIMARY KEY)")
        with pytest.raises(sqlite3.OperationalError):
            initialize_row_counts(con, ("files", "missing"))
        assert con.execute("SELECT name FROM sqlite_master WHERE name LIKE 'hub_count%'").fetchall() == []


@pytest.mark.parametrize("store_type", [CodeIndex, DeterministicEngine])
def test_global_status_uses_committed_counts_without_writer_lock_or_table_scan(tmp_path, monkeypatch, store_type):
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    store = store_type(config, repo_tools=object())
    with closing(store._connect()) as con:
        con.execute("INSERT INTO files(root,path,content_hash,language,updated_at) VALUES('repo','first.py','hash','python',0)")
        con.commit()
    connect = store._connect

    def restricted_connection():
        con = connect()
        con.set_authorizer(lambda action, table, *_: sqlite3.SQLITE_DENY
                           if action == sqlite3.SQLITE_READ and table in {
                               "files", "symbols", "refs", "edges", "facts", "dependencies", "scripts"
                           } else sqlite3.SQLITE_OK)
        return con

    monkeypatch.setattr(store, "_connect", restricted_connection)
    done = threading.Event()
    outcomes = []

    def read_status():
        try:
            outcomes.append(store.status())
        finally:
            done.set()

    reader = threading.Thread(target=read_status)
    try:
        with store._lock, closing(connect()) as writer:
            writer.execute("INSERT INTO files(root,path,content_hash,language,updated_at) VALUES('repo','uncommitted.py','hash','python',0)")
            reader.start()
            try:
                assert done.wait(5), "status waited for the index writer"
                assert outcomes[0]["success"] is True
                assert outcomes[0]["files"] == 1
            finally:
                writer.rollback()
    finally:
        if reader.ident is not None:
            reader.join(5)
            assert not reader.is_alive()
    # A fresh writer must enable REPLACE deletion triggers too; otherwise the
    # counter grows even though the primary key still identifies a single row.
    with closing(connect()) as writer:
        writer.execute("INSERT OR REPLACE INTO files(root,path,content_hash,language,updated_at) VALUES('repo','first.py','new-hash','python',1)")
        writer.commit()
    store._status_cache.clear()
    assert store.status()["files"] == 1
