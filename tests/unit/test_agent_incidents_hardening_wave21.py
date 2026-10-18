from __future__ import annotations

import logging
import math
import queue
import pytest
from local_ai_hub.agent_incidents import (
    IncidentFingerprint,
    IncidentRecord,
    RetryDecision,
    ToolOutcome,
    IncidentStore,
    _IncidentWebhookDispatcher,
)


def test_tool_outcome_boolean_and_null_byte_coercion():
    outcome = ToolOutcome(
        tool_name="tool\x00_test",
        command="run\x00 --flag",
        error="err\x00or",
        exit_code=1,
        state_revision="rev\x001",
        evidence_ids=("ev\x001", "  "),
        policy_blocked="truthy",  # type: ignore[arg-type]
        cancelled=1,  # type: ignore[arg-type]
        timed_out=None,  # type: ignore[arg-type]
        affected_paths=("path\x00/a", ""),
        repository_root="C:\\repo\x00dir",
    )
    assert outcome.tool_name == "tool_test"
    assert outcome.command == "run --flag"
    assert outcome.error == "error"
    assert outcome.state_revision == "rev1"
    assert outcome.evidence_ids == ("ev1",)
    assert outcome.affected_paths == ("path/a",)
    assert outcome.policy_blocked is True
    assert outcome.cancelled is True
    assert outcome.timed_out is False
    assert outcome.repository_root == "C:\\repodir"


@pytest.mark.parametrize("field", ["tenant", "tenant_key"])
@pytest.mark.parametrize("value", [None, False, ""])
def test_tool_outcome_rejects_retired_metadata_fields(field, value):
    with pytest.raises(ValueError, match="tenant fields were removed"):
        ToolOutcome(tool_name="cmd", metadata={field: value})


def test_tool_outcome_invalid_exit_code():
    with pytest.raises(ValueError, match="exit_code must be a signed or unsigned 32-bit integer"):
        ToolOutcome(tool_name="cmd", exit_code=True)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="exit_code must be a signed or unsigned 32-bit integer"):
        ToolOutcome(tool_name="cmd", exit_code=2**33)

    with pytest.raises(ValueError, match="exit_code must be a signed or unsigned 32-bit integer"):
        ToolOutcome(tool_name="cmd", exit_code="1")  # type: ignore[arg-type]


def test_incident_record_from_dict_and_roundtrip():
    fp = IncidentFingerprint(
        error_class="NotFoundError",
        operation_class="command",
        signature_hash="abcd1234efgh5678",
    )
    rec = IncidentRecord(
        incident_id="inc_test123",
        fingerprint=fp,
        operation_class="command",
        error_class="NotFoundError",
        redacted_message="file not found",
        state_revision="r1",
        attempts=3,
        evidence_ids=("ev1", "ev2"),
        root_cause="missing file",
        verified_fix="create file",
        confidence=0.9,
        resolved=True,
        ignored=False,
        created_at=100.0,
        updated_at=105.0,
        expires_at=200.0,
        affected_paths=("src/main.py",),
        repository_key="repokey",
    )
    data = rec.to_dict()
    assert isinstance(data, dict)
    assert data["incident_id"] == "inc_test123"
    assert data["status"] == "resolved"
    assert "tenant_key" not in data

    recovered = IncidentRecord.from_dict(data)
    assert recovered.incident_id == "inc_test123"
    assert recovered.fingerprint.signature_hash == "abcd1234efgh5678"
    assert recovered.root_cause == "missing file"
    assert recovered.verified_fix == "create file"
    assert recovered.confidence == 0.9
    with pytest.raises(ValueError, match="tenant fields were removed"):
        IncidentRecord.from_dict({**data, "tenant": None})
    assert recovered.resolved is True
    assert recovered.ignored is False
    assert recovered.repository_key == "repokey"

    # Non-mapping input fallback
    fallback = IncidentRecord.from_dict("invalid")  # type: ignore[arg-type]
    assert isinstance(fallback, IncidentRecord)
    assert fallback.incident_id.startswith("inc_")
    assert fallback.fingerprint.error_class == "unknown"


def test_incident_record_numeric_overflow_and_null_bytes():
    fp = IncidentFingerprint(
        error_class="Err\x00or",
        operation_class="op\x00class",
        signature_hash="hash\x00123",
    )
    assert fp.error_class == "Error"
    assert fp.operation_class == "opclass"
    assert fp.signature_hash == "hash123"

    rec = IncidentRecord(
        incident_id="inc_\x0001",
        fingerprint=fp,
        operation_class="cmd",
        error_class="Err",
        redacted_message="msg",
        state_revision="rev",
        attempts=float("inf"),  # type: ignore[arg-type]
        confidence="nan",  # type: ignore[arg-type]
        created_at=float("inf"),
        updated_at="invalid",  # type: ignore[arg-type]
        expires_at="inf",  # type: ignore[arg-type]
        resolved=1,  # type: ignore[arg-type]
        ignored=0,  # type: ignore[arg-type]
        repository_key="repo\x00key",
    )
    assert rec.incident_id == "inc_01"
    assert rec.attempts == 1
    assert rec.confidence == 0.0
    assert rec.created_at == 0.0
    assert rec.updated_at == 0.0
    assert rec.expires_at is None
    assert rec.resolved is True
    assert rec.ignored is False
    assert rec.repository_key == "repokey"


def test_retry_decision_invalid_action_and_from_dict():
    decision = RetryDecision(
        action="invalid\x00_action",
        reason="test reason\x00",
        confidence=1.5,
    )
    assert decision.action == "stop"
    assert decision.reason == "test reason"
    assert decision.confidence == 1.0

    d_dict = decision.to_dict()
    assert d_dict["action"] == "stop"

    recovered = RetryDecision.from_dict(d_dict)
    assert recovered.action == "stop"
    assert recovered.reason == "test reason"
    assert recovered.confidence == 1.0

    fallback = RetryDecision.from_dict(None)  # type: ignore[arg-type]
    assert fallback.action == "stop"


def test_incident_store_corrupted_row_handling(tmp_path):
    from local_ai_hub.agent_events import AgentStateStore

    state_store = AgentStateStore(db_path=tmp_path / "state.db", enabled=True)
    store = IncidentStore(state_store)

    corrupted_row = (
        "inc_corrupt",
        "command",
        "Error",
        "hash",
        "msg",
        "rev",
        "not_an_int",  # attempts
        "not_json",  # evidence_ids
        "rc",
        "fix",
        "not_a_float",  # confidence
        1,  # resolved
        "not_created_at",  # created_at
        "not_updated_at",  # updated_at
        "not_expires_at",  # expires_at
        "corrupted_affected_paths",
        0,  # ignored
        "repokey",
    )
    rec = store._row_to_record(corrupted_row)
    assert isinstance(rec, IncidentRecord)
    assert rec.incident_id == "inc_corrupt"
    assert rec.attempts == 1
    assert rec.evidence_ids == ()
    assert rec.affected_paths == ()
    assert rec.confidence == 0.0
    assert rec.created_at == 0.0
    assert rec.updated_at == 0.0
    assert rec.expires_at is None
    assert rec.resolved is True
    assert rec.repository_key == "repokey"


def test_incident_webhook_worker_logs_sender_failure(caplog):
    jobs = queue.Queue()
    jobs.put((("https://example.invalid/hook",), b"{}"))
    jobs.put(None)
    dispatcher = object.__new__(_IncidentWebhookDispatcher)
    dispatcher._jobs = jobs

    def fail_sender(_urls, _payload):
        raise RuntimeError("failure detail is not logged")

    dispatcher._sender = fail_sender
    with caplog.at_level(logging.WARNING, logger="local_ai_hub.agent_incidents"):
        dispatcher._run()

    assert "Incident webhook delivery failed (RuntimeError)" in caplog.text
    assert "failure detail is not logged" not in caplog.text
