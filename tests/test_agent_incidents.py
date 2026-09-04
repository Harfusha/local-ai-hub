from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_incidents import (
    IncidentFingerprint,
    IncidentRecord,
    IncidentStore,
    RetryDecision,
    ToolOutcome,
)


@pytest.fixture
def store(tmp_path: Path) -> IncidentStore:
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    return IncidentStore(state_store)


def failed_command_outcome(error: str, revision: str = "rev-1") -> ToolOutcome:
    return ToolOutcome(
        tool_name="command",
        command="python -m pytest",
        error=error,
        exit_code=1,
        state_revision=revision,
        evidence_ids=("ev-fail-1",),
    )


def test_same_error_signature_reuses_verified_fix_after_state_match(store: IncidentStore):
    incident = store.capture(failed_command_outcome("locked database"))
    assert incident is not None
    store.resolve(incident.incident_id, verified_fix="retry after busy backoff", confidence=0.95)
    decision = store.retry_decision(incident.fingerprint, incident.state_revision)
    assert decision.action == "apply_verified_fix"
    assert decision.verified_fix == "retry after busy backoff"


def test_negative_knowledge_stops_repeat_until_state_changes(store: IncidentStore):
    incident = store.capture(failed_command_outcome("invalid config", revision="rev-1"))
    assert incident is not None
    decision1 = store.retry_decision(incident.fingerprint, incident.state_revision)
    assert decision1.action == "stop"

    decision2 = store.retry_decision(incident.fingerprint, "changed_rev")
    assert decision2.action != "stop"


def test_policy_blocks_and_cancellations_do_not_produce_incidents(store: IncidentStore):
    blocked = ToolOutcome(
        tool_name="command",
        error="command blocked: not in allowlist",
        policy_blocked=True,
    )
    assert store.capture(blocked) is None

    cancelled = ToolOutcome(
        tool_name="command",
        cancelled=True,
    )
    assert store.capture(cancelled) is None
