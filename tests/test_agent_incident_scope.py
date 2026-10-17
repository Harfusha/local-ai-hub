from __future__ import annotations

from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_incidents import IncidentStore, ToolOutcome
from local_ai_hub.sqlite_support import connect_sqlite


def _capture(store: IncidentStore, root: Path, tenant: str, *, error: str = "same scoped failure"):
    return store.capture(
        ToolOutcome(
            tool_name="command",
            error=error,
            exit_code=1,
            metadata={"root_cause": "scope the failing operation", "verified_fix": "limit the retry"},
            repository_root=str(root),
            tenant=tenant,
        )
    )


@pytest.mark.parametrize("limit", [0, -1, 101, True, 1.5, "1", None])
def test_scoped_negative_knowledge_rejects_invalid_limits(tmp_path: Path, limit):
    store = IncidentStore(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    root = tmp_path / "repo"
    root.mkdir()
    _capture(store, root, "tenant-alpha")

    with pytest.raises(ValueError, match="limit"):
        store.find_negative_knowledge(
            "failure", limit=limit, root=str(root), tenant="tenant-alpha"
        )


@pytest.mark.parametrize("query", [None, 1, True, "", "  ", "bad\x00query"])
def test_scoped_negative_knowledge_rejects_invalid_queries(tmp_path: Path, query):
    store = IncidentStore(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    root = tmp_path / "repo"
    root.mkdir()

    with pytest.raises(ValueError, match="query"):
        store.find_negative_knowledge(query, root=str(root), tenant="tenant-alpha")


def test_scoped_negative_knowledge_requires_exact_repository_and_tenant(tmp_path: Path):
    store = IncidentStore(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    root_a = tmp_path / "repo-a"
    root_b = tmp_path / "repo-b"
    root_a.mkdir()
    root_b.mkdir()

    alpha_a = _capture(store, root_a, "tenant-alpha")
    beta_a = _capture(store, root_a, "tenant-beta")
    alpha_b = _capture(store, root_b, "tenant-alpha")

    found = store.find_negative_knowledge("scope", root=str(root_a), tenant="tenant-alpha")

    assert [item["incident_id"] for item in found] == [alpha_a.incident_id]
    assert found[0]["provenance"] == {
        "repository_key": alpha_a.repository_key,
        "tenant_key": alpha_a.tenant_key,
    }
    assert alpha_a.repository_key and alpha_a.tenant_key
    assert beta_a.incident_id != alpha_a.incident_id
    assert alpha_b.incident_id != alpha_a.incident_id
    assert store.find_negative_knowledge("scope", root=str(root_a), tenant="tenant-beta")[0]["incident_id"] == beta_a.incident_id
    assert store.find_negative_knowledge("scope", root=str(root_b), tenant="tenant-alpha")[0]["incident_id"] == alpha_b.incident_id


def test_scoped_negative_knowledge_hides_legacy_or_missing_tenant_rows(tmp_path: Path):
    store = IncidentStore(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    root = tmp_path / "repo"
    root.mkdir()
    legacy = store.capture(
        ToolOutcome(
            tool_name="command",
            error="legacy unscoped failure",
            exit_code=1,
            metadata={"verified_fix": "use a scoped retry"},
        )
    )
    scoped = _capture(store, root, "tenant-alpha", error="tenant scoped failure")

    assert store.find_negative_knowledge("failure", root=str(root), tenant="tenant-alpha")[0]["incident_id"] == scoped.incident_id
    assert store.find_negative_knowledge("failure") == []
    assert store.find_negative_knowledge("failure", root=str(root), tenant=None) == []
    assert store.find_negative_knowledge("failure", root=None, tenant="tenant-alpha") == []
    assert legacy is not None and legacy.repository_key == "" and legacy.tenant_key == ""
    assert store.find_negative_knowledge("failure", root=str(root), tenant="tenant-beta") == []


def test_scoped_negative_knowledge_skips_expired_records(tmp_path: Path):
    state = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store = IncidentStore(state)
    root = tmp_path / "repo"
    root.mkdir()
    incident = _capture(store, root, "tenant-alpha", error="expired scoped failure")

    with closing(connect_sqlite(state.db_path)) as con:
        con.execute("UPDATE agent_incidents SET expires_at = 1 WHERE incident_id = ?", (incident.incident_id,))
        con.commit()

    assert store.find_negative_knowledge("failure", root=str(root), tenant="tenant-alpha") == []


def test_agent_state_schema_preflight_accepts_incident_scope_index(tmp_path: Path):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    store = IncidentStore(state_store)
    root = tmp_path / "repo"
    root.mkdir()

    assert _capture(store, root, "tenant-alpha") is not None
    AgentStateStore(db_path)._ensure_schema()


def test_get_preserves_hashed_incident_scope_provenance(tmp_path: Path):
    store = IncidentStore(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    root = tmp_path / "repo"
    root.mkdir()
    incident = _capture(store, root, "tenant-alpha")

    loaded = store.get(incident.incident_id)

    assert loaded is not None
    assert loaded.repository_key == incident.repository_key
    assert loaded.tenant_key == incident.tenant_key
    assert str(root) not in repr(loaded.to_dict())
    assert "tenant-alpha" not in repr(loaded.to_dict())

def test_scoped_incident_attempts_do_not_aggregate_across_repository_or_tenant(tmp_path: Path):
    store = IncidentStore(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    root_a = tmp_path / "repo-a"
    root_b = tmp_path / "repo-b"
    root_a.mkdir()
    root_b.mkdir()

    first = _capture(store, root_a, "tenant-alpha")
    repeated = _capture(store, root_a, "tenant-alpha")
    other_repository = _capture(store, root_b, "tenant-alpha")
    other_tenant = _capture(store, root_a, "tenant-beta")

    assert repeated.incident_id == first.incident_id
    assert repeated.attempts == 2
    assert other_repository.incident_id != first.incident_id
    assert other_repository.attempts == 1
    assert other_tenant.incident_id != first.incident_id
    assert other_tenant.attempts == 1
