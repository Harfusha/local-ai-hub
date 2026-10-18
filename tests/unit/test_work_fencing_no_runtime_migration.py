from pathlib import Path
from contextlib import closing
import sqlite3

import pytest

from local_ai_hub.work_fencing import FencingLeaseStore, _FENCE_TABLE_DDL, _FENCE_INDEX_DDL


def test_incomplete_legacy_schema_refuses_without_rewrite(tmp_path: Path):
    path = tmp_path / "fences.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE writer_fence_counters(resource TEXT PRIMARY KEY, last_token INTEGER NOT NULL)")
        connection.execute("INSERT INTO writer_fence_counters VALUES ('repository', 7)")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="offline conversion"):
        FencingLeaseStore(path)
    assert path.read_bytes() == before
    assert not Path(str(path) + "-wal").exists()


def test_canonical_fences_open_without_runtime_migration(tmp_path: Path):
    store = FencingLeaseStore(tmp_path / "fences.sqlite3")
    with closing(sqlite3.connect(store.path)) as connection, connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(writer_fence_leases)")}
    assert {"scope_id", "work_id", "attempt_id", "attempt_token"}.issubset(columns)
    FencingLeaseStore(store.path)


def test_missing_scope_requires_explicit_conversion(tmp_path: Path):
    path = tmp_path / "fences.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        for ddl in (*_FENCE_TABLE_DDL.values(), *_FENCE_INDEX_DDL.values()):
            connection.execute(ddl)
        connection.execute("INSERT INTO writer_fence_leases(lease_id,resource,owner_id,fencing_token,expires_at,paths_json,active) VALUES ('lease','repository','task',1,100,'[\"a.py\"]',0)")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="no scope"):
        FencingLeaseStore(path)
    assert path.read_bytes() == before
