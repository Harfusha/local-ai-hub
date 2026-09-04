from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_incidents import IncidentStore, ToolOutcome


@pytest.fixture
def store(tmp_path: Path) -> IncidentStore:
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    return IncidentStore(state_store)


def test_auto_mint_negative_knowledge_missing_module(store: IncidentStore):
    outcome = ToolOutcome(
        tool_name="command",
        command="python -m myapp",
        error="ModuleNotFoundError: No module named 'fastapi'",
        exit_code=1,
        state_revision="rev-1",
    )
    incident = store.capture(outcome)
    assert incident is not None
    assert "fastapi" in (incident.root_cause or "")
    assert "install" in (incident.verified_fix or "")

    decision = store.retry_decision(incident.fingerprint, incident.state_revision)
    assert decision.action == "apply_verified_fix"
    assert "fastapi" in (decision.verified_fix or "")


def test_auto_mint_negative_knowledge_sqlite_lock(store: IncidentStore):
    outcome = ToolOutcome(
        tool_name="command",
        command="python migrate.py",
        error="sqlite3.OperationalError: database is locked",
        exit_code=1,
        state_revision="rev-2",
    )
    incident = store.capture(outcome)
    assert incident is not None
    assert "lock" in (incident.root_cause or "").lower()
    assert "backoff" in (incident.verified_fix or "").lower()


def test_find_negative_knowledge_by_query(store: IncidentStore):
    store.capture(ToolOutcome(
        tool_name="command",
        command="pytest",
        error="ModuleNotFoundError: No module named 'requests'",
        exit_code=1,
        state_revision="rev-3",
    ))
    results = store.find_negative_knowledge("requests")
    assert len(results) >= 1
    assert "requests" in results[0]["root_cause"]
