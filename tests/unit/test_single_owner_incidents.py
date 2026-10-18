"""Single-owner incidents retain repository separation without tenant partitions."""

import sqlite3
from contextlib import closing

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_incidents import IncidentRecord, IncidentStore, ToolOutcome


def _capture(store, root, agent="agent-a"):
    return store.capture(ToolOutcome(
        tool_name="command", command="python check.py", exit_code=1,
        error="SyntaxError: invalid syntax in module.py", state_revision="revision-one",
        repository_root=str(root), metadata={"agent": agent, "root_cause": "invalid syntax"},
    ))


@pytest.mark.parametrize("action", ("resolve", "ignore"))
def test_incident_mutations_do_not_cross_repository_scope(tmp_path, action):
    store = IncidentStore(AgentStateStore(tmp_path / "state.sqlite3"))
    first_root, other_root = tmp_path / "first", tmp_path / "other"
    first_root.mkdir()
    other_root.mkdir()
    first, other = _capture(store, first_root), _capture(store, other_root)
    assert first is not None and other is not None
    assert first.incident_id != other.incident_id
    if action == "resolve":
        store.resolve(first.incident_id, verified_fix="repair the syntax")
        assert store.get(first.incident_id).resolved is True
        assert store.get(other.incident_id).resolved is False
    else:
        store.set_ignored(first.incident_id)
        assert store.get(first.incident_id).ignored is True
        assert store.get(other.incident_id).ignored is False


def test_agents_share_incident_history_only_within_the_same_repository(tmp_path):
    store = IncidentStore(AgentStateStore(tmp_path / "state.sqlite3"))
    root = tmp_path / "repo"
    root.mkdir()
    first = _capture(store, root, "agent-a")
    second = _capture(store, root, "agent-b")
    assert first is not None and second is not None
    assert first.incident_id == second.incident_id
    assert second.attempts == 2
    assert set(second.to_dict()["provenance"]) == {"repository_key"}
    with closing(sqlite3.connect(store.state_store.db_path)) as connection, connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(agent_incidents)")}
    assert "tenant_key" not in columns


@pytest.mark.parametrize("value", (None, "", "retired", False))
def test_incident_records_reject_retired_provenance_by_presence(tmp_path, value):
    store = IncidentStore(AgentStateStore(tmp_path / "state.sqlite3"))
    record = _capture(store, tmp_path)
    assert record is not None
    data = record.to_dict()
    data["provenance"]["tenant_key"] = value
    with pytest.raises(ValueError, match="tenant fields were removed"):
        IncidentRecord.from_dict(data)
    with pytest.raises(ValueError, match="tenant fields were removed"):
        ToolOutcome(tool_name="command", metadata={"tenant": value})


@pytest.mark.parametrize("method", ("find_negative_knowledge", "retry_decision"))
def test_incident_repository_operations_require_root_before_access(method):
    store = object.__new__(IncidentStore)
    args = ("syntax",) if method == "find_negative_knowledge" else (object(), "revision")
    with pytest.raises(TypeError):
        getattr(store, method)(*args)
    with pytest.raises(ValueError, match="root must be"):
        getattr(store, method)(*args, root="")
    with pytest.raises(TypeError, match="tenant"):
        getattr(store, method)(*args, root="repo", tenant="retired")
