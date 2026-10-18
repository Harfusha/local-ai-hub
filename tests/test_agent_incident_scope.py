from __future__ import annotations

from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_incidents import IncidentStore, ToolOutcome
from local_ai_hub.sqlite_support import connect_sqlite


def _capture(store: IncidentStore, root: Path, *, error: str = "same scoped failure"):
    return store.capture(
        ToolOutcome(
            tool_name="command",
            error=error,
            exit_code=1,
            metadata={"root_cause": "scope the failing operation", "verified_fix": "limit the retry"},
            repository_root=str(root),
        )
    )


@pytest.mark.parametrize("limit", [0, -1, 101, True, 1.5, "1", None])
def test_scoped_negative_knowledge_rejects_invalid_limits(tmp_path: Path, limit):
    store = IncidentStore(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    root = tmp_path / "repo"
    root.mkdir()
    _capture(store, root)

    with pytest.raises(ValueError, match="limit"):
        store.find_negative_knowledge(
            "failure", limit=limit, root=str(root)
        )


@pytest.mark.parametrize("query", [None, 1, True, "", "  ", "bad\x00query"])
def test_scoped_negative_knowledge_rejects_invalid_queries(tmp_path: Path, query):
    store = IncidentStore(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    root = tmp_path / "repo"
    root.mkdir()

    with pytest.raises(ValueError, match="query"):
        store.find_negative_knowledge(query, root=str(root))


def test_scoped_negative_knowledge_requires_exact_repository(tmp_path: Path):
    store = IncidentStore(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    root_a = tmp_path / "repo-a"
    root_b = tmp_path / "repo-b"
    root_a.mkdir()
    root_b.mkdir()

    alpha_a = _capture(store, root_a)
    alpha_b = _capture(store, root_b)

    found = store.find_negative_knowledge("scope", root=str(root_a))

    assert [item["incident_id"] for item in found] == [alpha_a.incident_id]
    assert found[0]["provenance"] == {
        "repository_key": alpha_a.repository_key,
    }
    assert alpha_a.repository_key
    assert alpha_b.incident_id != alpha_a.incident_id
    assert store.find_negative_knowledge("scope", root=str(root_b))[0]["incident_id"] == alpha_b.incident_id


def test_repository_negative_knowledge_excludes_owner_global_incidents(tmp_path: Path):
    store = IncidentStore(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    root = tmp_path / "repo"
    root.mkdir()
    global_incident = store.capture(
        ToolOutcome(
            tool_name="command",
            error="owner global failure",
            exit_code=1,
            metadata={"verified_fix": "use a scoped retry"},
        )
    )
    scoped = _capture(store, root, error="repository scoped failure")

    assert store.find_negative_knowledge("failure", root=str(root))[0]["incident_id"] == scoped.incident_id
    with pytest.raises(TypeError):
        store.find_negative_knowledge("failure")
    with pytest.raises(ValueError):
        store.find_negative_knowledge("failure", root=None)
    assert global_incident is not None and global_incident.repository_key == ""


def test_scoped_negative_knowledge_skips_expired_records(tmp_path: Path):
    state = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store = IncidentStore(state)
    root = tmp_path / "repo"
    root.mkdir()
    incident = _capture(store, root, error="expired scoped failure")

    with closing(connect_sqlite(state.db_path)) as con:
        con.execute("UPDATE agent_incidents SET expires_at = 1 WHERE incident_id = ?", (incident.incident_id,))
        con.commit()

    assert store.find_negative_knowledge("failure", root=str(root)) == []


def test_agent_state_schema_preflight_accepts_incident_scope_index(tmp_path: Path):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    store = IncidentStore(state_store)
    root = tmp_path / "repo"
    root.mkdir()

    assert _capture(store, root) is not None
    AgentStateStore(db_path)._ensure_schema()


def test_get_preserves_hashed_incident_scope_provenance(tmp_path: Path):
    store = IncidentStore(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    root = tmp_path / "repo"
    root.mkdir()
    incident = _capture(store, root)

    loaded = store.get(incident.incident_id)

    assert loaded is not None
    assert loaded.repository_key == incident.repository_key
    assert str(root) not in repr(loaded.to_dict())
    assert "tenant_key" not in loaded.to_dict()

def test_incident_attempts_aggregate_only_within_repository(tmp_path: Path):
    store = IncidentStore(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    root_a = tmp_path / "repo-a"
    root_b = tmp_path / "repo-b"
    root_a.mkdir()
    root_b.mkdir()

    first = _capture(store, root_a)
    repeated = _capture(store, root_a)
    other_repository = _capture(store, root_b)

    assert repeated.incident_id == first.incident_id
    assert repeated.attempts == 2
    assert other_repository.incident_id != first.incident_id
    assert other_repository.attempts == 1
