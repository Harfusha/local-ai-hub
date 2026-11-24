import sqlite3
import threading
from contextlib import closing

import pytest

from local_ai_hub import preprocess_lexical
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.state_lifecycle import write_state_version
from tools.state_migrations import run_state_migrations


def _open_preprocessor(tmp_path):
    pre = object.__new__(ProjectPreprocessor)
    pre.db_path = tmp_path / "preprocess.sqlite3"
    pre._db_lock = threading.RLock()
    pre._sqlite_busy_seconds = 1
    pre._init_db()
    return pre


def test_fresh_lexical_index_shares_payloads_and_preserves_rank_after_restart(tmp_path):
    pre = _open_preprocessor(tmp_path)
    rows = [
        ("root-a", "source.py", "same", "route route"),
        ("root-b", "source.py", "same", "route route"),
        ("root-c", "source.py", "same", "route projection"),
        ("root-a", "aux.py", "different", "route other"),
    ]
    with closing(pre._connect()) as con, con:
        con.executemany(
            "INSERT INTO file_refs(root,path,content_hash,size,generation,updated_at) VALUES(?,?,?,1,1,1)",
            [(root, path, digest) for root, path, digest, _ in rows],
        )
        con.executemany(
            "INSERT INTO source_index(root,path,content_hash,text,updated_at) VALUES(?,?,?,?,1)", rows,
        )
        for root in ("root-a", "root-b", "root-c", "root-a"):
            pre._link_missing_fts_rows(con, root)
        assert con.execute("SELECT COUNT(*) FROM source_fts_bindings").fetchone()[0] == 4
        assert con.execute("SELECT COUNT(*) FROM source_fts_documents").fetchone()[0] == 3

    pre = _open_preprocessor(tmp_path)
    with closing(pre._connect()) as con, con:
        match = '"route" OR "route route"'
        assert pre._ranked_lexical_paths(con, "root-a", match, 2) == ["source.py", "aux.py"]
        con.execute("UPDATE file_refs SET needs_hash=1 WHERE root='root-a' AND path='source.py'")
        assert pre._ranked_lexical_paths(con, "root-a", match, 1) == ["aux.py"]
        con.execute("DELETE FROM source_fts_bindings WHERE root='root-a' AND path='source.py'")
        assert con.execute("SELECT COUNT(*) FROM source_fts_documents").fetchone()[0] == 3
        con.execute("DELETE FROM source_fts_bindings WHERE root='root-b'")
        assert con.execute("SELECT COUNT(*) FROM source_fts_documents").fetchone()[0] == 2
        con.execute("INSERT INTO source_fts(source_fts,rank) VALUES('integrity-check',1)")


def test_shared_fts_rolls_back_and_retries_after_a_later_batch_fails(tmp_path, monkeypatch):
    pre = _open_preprocessor(tmp_path)
    monkeypatch.setattr(preprocess_lexical, "_WRITE_BATCH_ROWS", 1)
    rows = [("root-a", "first.py", "needle"), ("root-a", "second.py", "needle")]
    with closing(pre._connect()) as con:
        con.execute("""CREATE TEMP TRIGGER fail_second BEFORE INSERT ON source_fts_bindings
            WHEN new.path='second.py' BEGIN SELECT RAISE(ABORT,'failed second FTS batch'); END""")
        with pytest.raises(sqlite3.IntegrityError, match="failed second FTS batch"), con:
            pre._insert_fts_rows(con, rows)
        assert con.execute("SELECT COUNT(*) FROM source_fts_documents").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM source_fts WHERE source_fts MATCH 'needle'").fetchone()[0] == 0

        con.execute("DROP TRIGGER fail_second")
        with con:
            pre._insert_fts_rows(con, rows)
            assert con.execute("SELECT COUNT(*) FROM source_fts_documents").fetchone()[0] == 1
            assert [row[0] for row in con.execute(
                "SELECT path FROM source_fts WHERE source_fts MATCH 'needle' ORDER BY rowid"
            )] == ["first.py", "second.py"]
            con.execute("INSERT INTO source_fts(source_fts,rank) VALUES('integrity-check',1)")


def test_legacy_fts_is_migrated_offline_before_runtime_open(tmp_path, monkeypatch):
    monkeypatch.setattr(preprocess_lexical, "_MIGRATION_BATCH_ROWS", 1, raising=False)
    write_state_version(tmp_path, version=6)
    db_path = tmp_path / "preprocess.sqlite3"
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute("CREATE VIRTUAL TABLE source_fts USING fts5(root UNINDEXED,path UNINDEXED,content)")
        con.executemany("INSERT INTO source_fts(rowid,root,path,content) VALUES(?,?,?,?)", [
            (-2, None, None, None),
            (4, "a", "same.py", "needle needle"),
            (5, "a", "same.py", "needle needle"),
            (8, "b", "same.py", "needle needle"),
            (9, "b", "same.py", "needle needle"),
            (10, "a", "old.py", "needle"),
        ])
    result = run_state_migrations(tmp_path)
    assert result["status"] == "migrated"
    pre = _open_preprocessor(tmp_path)
    with closing(pre._connect()) as con:
        assert preprocess_lexical.fts_layout(con) == preprocess_lexical.SHARED_FTS_ROWS
        assert not preprocess_lexical.has_retired_fts(con)
        assert con.execute("SELECT rowid,root,path,content FROM source_fts WHERE rowid=-2").fetchone()[:] == (-2, None, None, None)
        assert con.execute("SELECT COUNT(*) FROM source_fts WHERE source_fts MATCH 'needle'").fetchone()[0] == 5
        assert con.execute("SELECT COUNT(*) FROM source_fts_documents").fetchone()[0] == 3
        con.execute("INSERT INTO source_fts(source_fts,rank) VALUES('integrity-check',1)")


def test_runtime_start_rejects_legacy_fts_before_migration(tmp_path):
    write_state_version(tmp_path, version=6)
    with closing(sqlite3.connect(tmp_path / "preprocess.sqlite3")) as con, con:
        con.execute("CREATE VIRTUAL TABLE source_fts USING fts5(root UNINDEXED,path UNINDEXED,content)")
        con.execute("INSERT INTO source_fts VALUES('a','kept.py','needle')")
    with pytest.raises(sqlite3.DatabaseError, match="update-time lexical-index migration"):
        _open_preprocessor(tmp_path)
    with closing(sqlite3.connect(tmp_path / "preprocess.sqlite3")) as con:
        assert con.execute("SELECT path FROM source_fts WHERE source_fts MATCH 'needle'").fetchone() == ("kept.py",)
        assert con.execute("SELECT name FROM sqlite_master WHERE name='source_fts_migration'").fetchone() is None
