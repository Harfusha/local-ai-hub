import sqlite3
from contextlib import closing

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_incidents import IncidentStore
from local_ai_hub.leases import ScopeLeaseStore
from local_ai_hub.sqlite_support import DurableSchemaMismatchError


def test_fresh_shared_database_reopens_canonical_event_and_incident_schema(tmp_path):
    state_dir = tmp_path / "state"
    ScopeLeaseStore(state_dir)
    db_path = state_dir / "agent_state.sqlite"

    store = AgentStateStore(db_path)
    store._ensure_schema()
    IncidentStore(store)
    reopened = AgentStateStore(db_path)
    reopened._ensure_schema()

    with closing(sqlite3.connect(db_path)) as con:
        tables = {
            str(row[0])
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not str(row[0]).startswith("sqlite_")
        }
        assert {
            "agent_events", "agent_snapshots", "leases", "lease_waits", "agent_incidents"
        } <= tables
        assert "agent_event_schema_versions" not in tables
        assert con.execute("PRAGMA user_version").fetchone() == (store._SCHEMA_VERSION,)


def test_incompatible_schema_rejects_without_writing_or_backup(tmp_path):
    db_path = tmp_path / "agent_state.sqlite"
    with closing(sqlite3.connect(db_path)) as con:
        con.execute("CREATE TABLE unrelated_legacy_state (value TEXT)")
        con.execute("INSERT INTO unrelated_legacy_state VALUES ('preserve')")
        con.commit()
    original = db_path.read_bytes()

    with pytest.raises(DurableSchemaMismatchError):
        AgentStateStore(db_path)._ensure_schema()

    assert db_path.read_bytes() == original
    assert not list(tmp_path.glob("*.bak"))
