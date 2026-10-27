from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_incidents import IncidentStore, ToolOutcome


@pytest.fixture
def store(tmp_path: Path) -> IncidentStore:
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite")
    return IncidentStore(state_store)


def test_auto_mint_negative_knowledge_missing_module(store: IncidentStore, tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    outcome = ToolOutcome(
        tool_name="command",
        command="python -m myapp",
        error="ModuleNotFoundError: No module named 'fastapi'",
        exit_code=1,
        state_revision="rev-1",
        repository_root=str(root),
    )
    incident = store.capture(outcome)
    assert incident is not None
    assert "fastapi" in (incident.root_cause or "")
    assert incident.verified_fix is None
    assert "install" in (incident.suggested_fix or "")

    decision = store.retry_decision(incident.fingerprint, incident.state_revision, root=str(root))
    assert decision.action == "stop"
    assert decision.verified_fix is None


def test_auto_mint_negative_knowledge_sqlite_lock(store: IncidentStore, tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    outcome = ToolOutcome(
        tool_name="command",
        command="python migrate.py",
        error="sqlite3.OperationalError: database is locked",
        exit_code=1,
        state_revision="rev-2",
        repository_root=str(root),
    )
    incident = store.capture(outcome)
    assert incident is not None
    assert "lock" in (incident.root_cause or "").lower()
    assert incident.verified_fix is None
    assert "backoff" in (incident.suggested_fix or "").lower()
    found = store.find_negative_knowledge("backoff", root=str(root))
    assert len(found) == 1
    assert found[0]["verified_fix"] == ""
    assert "backoff" in found[0]["suggested_fix"].lower()


def test_find_negative_knowledge_by_query(store: IncidentStore, tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    store.capture(ToolOutcome(
        tool_name="command",
        command="pytest",
        error="ModuleNotFoundError: No module named 'requests'",
        exit_code=1,
        state_revision="rev-3",
        repository_root=str(root),
    ))
    results = store.find_negative_knowledge("requests", root=str(root))
    assert len(results) >= 1
    assert "requests" in results[0]["root_cause"]


def test_command_broker_skips_unscoped_known_pitfalls(tmp_path: Path):
    from local_ai_hub.commands import CommandBroker
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite")
    store = IncidentStore(state_store)

    store.capture(ToolOutcome(
        tool_name="command",
        command="pytest tests/test_broken.py",
        error="ModuleNotFoundError: No module named 'numpy'",
        exit_code=1,
        state_revision="rev-4",
    ))

    cb = CommandBroker({"server": {"state_dir": str(tmp_path)}}, repo_state=None)
    cb.set_incident_store(store)

    cb._execute = lambda *args, **kwargs: {"success": True, "exit_code": 0, "stdout": "", "stderr": ""}
    cb.classify = lambda *args, **kwargs: {"class": "validation", "cacheable": False, "allowed": True}

    res = cb.run("pytest tests/test_broken.py", str(tmp_path))
    assert 'known_pitfalls' not in res
