import sqlite3
from contextlib import closing

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.leases import ScopeLeaseStore


def test_fresh_lease_database_adds_event_schema_without_backup(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    ScopeLeaseStore(state_dir)
    db_path = state_dir / "agent_state.sqlite"

    def unexpected_backup(cls, source):
        raise AssertionError("fresh auxiliary-only database must not be backed up")

    monkeypatch.setattr(
        AgentStateStore,
        "_verified_backup",
        classmethod(unexpected_backup),
    )

    store = AgentStateStore(db_path)
    store._ensure_schema()

    with closing(sqlite3.connect(db_path)) as con:
        tables = {
            str(row[0])
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not str(row[0]).startswith("sqlite_")
        }
        assert {"agent_events", "agent_snapshots", "leases", "lease_waits"} <= tables
        assert con.execute("PRAGMA user_version").fetchone() == (store._SCHEMA_VERSION,)
        assert con.execute("SELECT 1 FROM leases LIMIT 1").fetchone() is None
        assert con.execute("SELECT 1 FROM lease_waits LIMIT 1").fetchone() is None


def test_auxiliary_database_with_lease_data_keeps_backup_gate(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    ScopeLeaseStore(state_dir)
    db_path = state_dir / "agent_state.sqlite"
    with closing(sqlite3.connect(db_path)) as con:
        con.execute(
            """INSERT INTO leases (
                   lease_id, tenant, root_id, root_path, path, purpose, created_at, expires_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("lease-1", "tenant-a", "root-1", "repo", "src/file.py", "repository_search", 1.0, 2.0),
        )
        con.commit()

    backups = []

    def record_backup(cls, source):
        backups.append(source.execute("SELECT 1 FROM leases LIMIT 1").fetchone())

    monkeypatch.setattr(
        AgentStateStore,
        "_verified_backup",
        classmethod(record_backup),
    )

    store = AgentStateStore(db_path)
    store._ensure_schema()

    assert backups == [(1,)]
    with closing(sqlite3.connect(db_path)) as con:
        assert con.execute(
            "SELECT lease_id, path FROM leases WHERE lease_id = ?", ("lease-1",)
        ).fetchone() == ("lease-1", "src/file.py")


def test_nonempty_lease_waits_keeps_backup_gate(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    ScopeLeaseStore(state_dir)
    db_path = state_dir / "agent_state.sqlite"
    with closing(sqlite3.connect(db_path)) as con:
        con.execute(
            """INSERT INTO lease_waits (
                   tenant, blocked_by, root_id, requested_path, updated_at
               ) VALUES (?, ?, ?, ?, ?)""",
            ("tenant-a", "lease-1", "root-1", "src/file.py", 1.0),
        )
        con.commit()

    backups = []

    def record_backup(cls, source):
        backups.append(source.execute("SELECT 1 FROM lease_waits LIMIT 1").fetchone())

    monkeypatch.setattr(
        AgentStateStore,
        "_verified_backup",
        classmethod(record_backup),
    )

    store = AgentStateStore(db_path)
    store._ensure_schema()

    assert backups == [(1,)]
    with closing(sqlite3.connect(db_path)) as con:
        assert con.execute(
            "SELECT tenant, requested_path FROM lease_waits WHERE blocked_by = ?",
            ("lease-1",),
        ).fetchone() == ("tenant-a", "src/file.py")


def test_schema_change_before_immediate_lock_fails_closed_without_version_commit(
    tmp_path, monkeypatch
):
    state_dir = tmp_path / "state"
    ScopeLeaseStore(state_dir)
    db_path = state_dir / "agent_state.sqlite"
    original_pristine_check = AgentStateStore._is_pristine_auxiliary_database
    inserted = False

    def insert_schema_change(con, schema):
        nonlocal inserted
        pristine = original_pristine_check(con, schema)
        if not inserted:
            inserted = True
            with closing(sqlite3.connect(db_path)) as writer:
                writer.execute("CREATE TABLE concurrent_marker (id INTEGER PRIMARY KEY)")
                writer.commit()
        return pristine

    monkeypatch.setattr(
        AgentStateStore,
        "_is_pristine_auxiliary_database",
        staticmethod(insert_schema_change),
    )

    with closing(sqlite3.connect(db_path)) as con:
        with pytest.raises(RuntimeError, match="unsupported agent_state schema object"):
            AgentStateStore._migrate_known_schema(con, existed_before_open=True)
        assert con.execute("PRAGMA user_version").fetchone() == (0,)
        assert con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_events'"
        ).fetchone() is None


def test_row_change_before_immediate_lock_fails_closed_without_version_commit(
    tmp_path, monkeypatch
):
    state_dir = tmp_path / "state"
    ScopeLeaseStore(state_dir)
    db_path = state_dir / "agent_state.sqlite"
    original_pristine_check = AgentStateStore._is_pristine_auxiliary_database
    inserted = False

    def insert_row_change(con, schema):
        nonlocal inserted
        pristine = original_pristine_check(con, schema)
        if not inserted:
            inserted = True
            with closing(sqlite3.connect(db_path)) as writer:
                writer.execute(
                    """INSERT INTO lease_waits (
                           tenant, blocked_by, root_id, requested_path, updated_at
                       ) VALUES (?, ?, ?, ?, ?)""",
                    ("tenant-a", "lease-race", "root-race", "src/race.py", 1.0),
                )
                writer.commit()
        return pristine

    monkeypatch.setattr(
        AgentStateStore,
        "_is_pristine_auxiliary_database",
        staticmethod(insert_row_change),
    )

    with closing(sqlite3.connect(db_path)) as con:
        with pytest.raises(RuntimeError, match="changed before fresh schema initialization"):
            AgentStateStore._migrate_known_schema(con, existed_before_open=True)
        assert con.execute("PRAGMA user_version").fetchone() == (0,)
        assert con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_events'"
        ).fetchone() is None
        assert con.execute(
            "SELECT tenant FROM lease_waits WHERE blocked_by = ?", ("lease-race",)
        ).fetchone() == ("tenant-a",)
