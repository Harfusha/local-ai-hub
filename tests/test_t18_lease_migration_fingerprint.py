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


def test_scope_leases_migrate_into_versioned_agent_state_database(tmp_path):
    legacy = tmp_path / "leases.sqlite3"
    lease_row = ("lease-1", "owner", "project:one", "root", "src/a.py", "test", 10.0, 20.0)
    wait_row = ("waiter", "owner", "project:one", "src/a.py", 11.0)
    with closing(sqlite3.connect(legacy)) as con:
        con.execute('''CREATE TABLE leases (
            lease_id TEXT NOT NULL, tenant TEXT NOT NULL, root_id TEXT NOT NULL,
            root_path TEXT NOT NULL, path TEXT NOT NULL, purpose TEXT NOT NULL,
            created_at REAL NOT NULL, expires_at REAL NOT NULL,
            PRIMARY KEY(lease_id, path))''')
        con.execute('''CREATE TABLE lease_waits (
            tenant TEXT NOT NULL, blocked_by TEXT NOT NULL, root_id TEXT NOT NULL,
            requested_path TEXT NOT NULL, updated_at REAL NOT NULL,
            PRIMARY KEY(tenant, blocked_by, requested_path))''')
        con.execute("INSERT INTO leases VALUES(?,?,?,?,?,?,?,?)", lease_row)
        con.execute("INSERT INTO lease_waits VALUES(?,?,?,?,?)", wait_row)
        con.commit()
    legacy_bytes = legacy.read_bytes()
    leases = ScopeLeaseStore(tmp_path)
    with closing(sqlite3.connect(leases.path)) as con:
        sql = con.execute("SELECT sql FROM sqlite_master WHERE name='lease_waits'").fetchone()[0]
        assert hashlib.sha256(" ".join(sql.split()).casefold().encode()).hexdigest() == RENAMED_WAIT_HASH
        assert con.execute("SELECT * FROM leases").fetchall() == [lease_row]
        assert con.execute("SELECT * FROM lease_waits").fetchall() == [wait_row]
        assert dict((row[1], row[5]) for row in con.execute("PRAGMA table_info(lease_waits)"))["root_id"] == 1

    AgentStateStore(leases.path)._ensure_schema()
    restarted = ScopeLeaseStore(tmp_path)
    AgentStateStore(restarted.path)._ensure_schema()
    with closing(sqlite3.connect(restarted.path)) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == AgentStateStore._SCHEMA_VERSION
        assert con.execute("SELECT * FROM leases").fetchall() == [lease_row]
        assert con.execute("SELECT * FROM lease_waits").fetchall() == [wait_row]
        assert con.execute("SELECT COUNT(*) FROM agent_state_migrations").fetchone()[0] == 1
    assert legacy.read_bytes() == legacy_bytes


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
