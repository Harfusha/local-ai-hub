from contextlib import closing
import hashlib
import sqlite3

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.leases import ScopeLeaseStore


# Exact sqlite_master output of leases.py's namespace-key migration/rename.
RENAMED_WAIT_DDL = '''CREATE TABLE "lease_waits" (
    tenant TEXT NOT NULL,
    blocked_by TEXT NOT NULL,
    root_id TEXT NOT NULL,
    requested_path TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY(root_id, tenant, blocked_by, requested_path)
)'''
RENAMED_WAIT_HASH = "314dbe78e360c6c00133c85323b9349936d9cb2e87121e60c8ffb733b46d20aa"


def test_scope_leases_reject_legacy_database_without_writes(tmp_path):
    from local_ai_hub.sqlite_support import UnsupportedLegacyStateDatabase

    legacy = tmp_path / "leases.sqlite3"
    with closing(sqlite3.connect(legacy)) as con, con:
        con.execute("CREATE TABLE leases (lease_id TEXT PRIMARY KEY)")
        con.execute("INSERT INTO leases VALUES ('lease-1')")
    legacy_bytes = legacy.read_bytes()

    with pytest.raises(UnsupportedLegacyStateDatabase, match="unsupported legacy durable state database"):
        ScopeLeaseStore(tmp_path)

    assert legacy.read_bytes() == legacy_bytes
    assert not (tmp_path / "agent_state.sqlite").exists()


def test_scope_leases_ignore_archived_legacy_database_when_canonical_exists(tmp_path):
    canonical = tmp_path / "agent_state.sqlite"
    AgentStateStore(canonical)._ensure_schema()
    archived = tmp_path / "leases.sqlite3"
    archived.write_bytes(b"archived legacy lease database")

    leases = ScopeLeaseStore(tmp_path)

    assert leases.path == canonical
    assert archived.read_bytes() == b"archived legacy lease database"

def test_exact_renamed_wait_schema_is_classified_without_mutation():
    with closing(sqlite3.connect(":memory:")) as con:
        con.execute(RENAMED_WAIT_DDL)
        before = list(con.execute("SELECT type,name,sql FROM sqlite_master"))
        assert AgentStateStore._classify_schema(con)
        assert list(con.execute("SELECT type,name,sql FROM sqlite_master")) == before


@pytest.mark.parametrize("ddl", [
    RENAMED_WAIT_DDL.replace("root_id TEXT NOT NULL", "root_id TEXT"),
    RENAMED_WAIT_DDL.replace("PRIMARY KEY(root_id, tenant", "PRIMARY KEY(tenant"),
    RENAMED_WAIT_DDL.replace("updated_at REAL NOT NULL", "updated_at REAL NOT NULL CHECK(updated_at > 0)"),
    RENAMED_WAIT_DDL.replace("updated_at REAL NOT NULL", "updated_at REAL NOT NULL DEFAULT 0"),
])
def test_changed_renamed_wait_constraints_remain_rejected(ddl):
    with closing(sqlite3.connect(":memory:")) as con:
        con.execute(ddl)
        with pytest.raises(RuntimeError, match="unsupported agent_state schema object definition: table lease_waits"):
            AgentStateStore._classify_schema(con)


def test_renamed_wait_schema_does_not_allow_unknown_trigger():
    with closing(sqlite3.connect(":memory:")) as con:
        con.execute(RENAMED_WAIT_DDL)
        con.execute("CREATE TRIGGER unexpected AFTER INSERT ON lease_waits BEGIN SELECT 1; END")
        with pytest.raises(RuntimeError, match="unsupported agent_state schema object: trigger unexpected"):
            AgentStateStore._classify_schema(con)


def test_changed_wait_schema_preflight_preserves_database_bytes(tmp_path):
    path = tmp_path / "untrusted.sqlite"
    with closing(sqlite3.connect(path)) as con:
        con.execute(RENAMED_WAIT_DDL.replace("root_id TEXT NOT NULL", "root_id TEXT"))
        con.commit()
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="unsupported agent_state schema object definition: table lease_waits"):
        AgentStateStore(path)._preflight_schema_read_only()
    assert path.read_bytes() == before
