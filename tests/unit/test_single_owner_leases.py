"""Writer leases remain distinct from removed human tenancy."""

from contextlib import closing, contextmanager
import sqlite3

import pytest

from local_ai_hub import leases as leases_module
from local_ai_hub.leases import ScopeLeaseStore


def test_actual_writers_conflict_without_cross_repository_leakage(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    store = ScopeLeaseStore(tmp_path / "state")
    held = store.claim(owner="task-one:execution-one", root=str(first), paths=["source.py"])
    assert held["success"]
    blocked = store.claim(owner="task-two:execution-two", root=str(first), paths=["source.py"])
    assert not blocked["success"]
    assert blocked["conflicts"][0]["owner"] == "task-one:execution-one"
    assert "tenant" not in blocked["conflicts"][0]
    assert store.claim(owner="task-two:execution-two", root=str(second), paths=["source.py"])["success"]
    assert not store.renew(owner="task-two:execution-two", lease_id=held["lease_id"])["success"]
    assert store.release(owner="task-two:execution-two", lease_id=held["lease_id"])["released_rows"] == 0
    assert store.release(owner="task-one:execution-one", lease_id=held["lease_id"])["released_rows"] == 1


def test_lease_mutations_use_bounded_write_transactions(tmp_path, monkeypatch):
    store = ScopeLeaseStore(tmp_path / "state")
    original = leases_module.write_transaction
    labels = []

    @contextmanager
    def observed_transaction(connection, **kwargs):
        labels.append(kwargs.get("rollback_label"))
        with original(connection, **kwargs) as transaction:
            yield transaction

    monkeypatch.setattr(leases_module, "write_transaction", observed_transaction)

    held = store.claim(owner="writer-a", root=str(tmp_path), paths=["src/a.py"])
    blocked = store.claim(owner="writer-b", root=str(tmp_path), paths=["src/a.py"])
    renewed = store.renew(owner="writer-a", lease_id=held["lease_id"])
    released = store.release(owner="writer-a", lease_id=held["lease_id"])
    reaped = store.reap_expired()

    assert held["success"] is True
    assert blocked["success"] is False
    assert renewed["success"] is True
    assert released["released_rows"] == 1
    assert reaped["success"] is True
    assert labels == [
        "writer lease claim",
        "writer lease claim",
        "writer lease renew",
        "writer lease release",
        "writer lease reap",
    ]


def test_expired_lease_does_not_block_new_claim(tmp_path):
    store = ScopeLeaseStore(tmp_path / "state")
    held = store.claim(owner="writer-a", root=str(tmp_path), paths=["src/a.py"])
    with closing(store._connect()) as connection:
        connection.execute(
            "UPDATE leases SET expires_at=0 WHERE lease_id=?",
            (held["lease_id"],),
        )
        connection.commit()

    replacement = store.claim(owner="writer-b", root=str(tmp_path), paths=["src/a.py"])

    assert replacement["success"] is True


@pytest.mark.parametrize("method,arguments", [
    ("claim", {"owner": "writer", "root": "root", "paths": ["file"]}),
    ("claim_batch", {"owner": "writer", "root": "root", "paths": ["file"]}),
    ("release", {"owner": "writer", "lease_id": "lease"}),
    ("renew", {"owner": "writer", "lease_id": "lease"}),
    ("check_path", {"path": "file"}),
])
@pytest.mark.parametrize("value", [None, False, "", "former-tenant"])
def test_retired_namespace_arguments_reject_before_database_access(method, arguments, value):
    with pytest.raises(TypeError, match="tenant"):
        getattr(ScopeLeaseStore.__new__(ScopeLeaseStore), method)(**arguments, tenant=value)


def test_owner_is_required_and_old_positional_contract_is_gone():
    store = ScopeLeaseStore.__new__(ScopeLeaseStore)
    with pytest.raises(TypeError):
        store.claim("former-tenant", "root", ["file"])
    assert not hasattr(store, "release_tenant")
    assert not store.claim(owner=" writer ", root="root", paths=["file"])["success"]


def test_tenant_shaped_durable_leases_require_offline_conversion(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    path = state / "agent_state.sqlite"
    with closing(sqlite3.connect(path)) as con:
        con.execute("""CREATE TABLE leases (
            lease_id TEXT NOT NULL, tenant TEXT NOT NULL, root_id TEXT NOT NULL,
            root_path TEXT NOT NULL, path TEXT NOT NULL, purpose TEXT NOT NULL,
            created_at REAL NOT NULL, expires_at REAL NOT NULL, PRIMARY KEY(lease_id,path)
        )""")
        con.execute("""CREATE TABLE lease_waits (
            tenant TEXT NOT NULL, blocked_by TEXT NOT NULL, root_id TEXT NOT NULL,
            requested_path TEXT NOT NULL, updated_at REAL NOT NULL,
            PRIMARY KEY(root_id,tenant,blocked_by,requested_path)
        )""")
        con.execute("INSERT INTO leases VALUES (?,?,?,?,?,?,?,?)",
                    ("preserve", "old-label", "root-id", str(tmp_path), "file", "saved-work", 1, 9999999999))
        con.commit()
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="schema mismatch"):
        ScopeLeaseStore(state)
    assert path.read_bytes() == before
    with closing(sqlite3.connect(path)) as con:
        assert con.execute("SELECT tenant, purpose FROM leases").fetchall() == [("old-label", "saved-work")]
