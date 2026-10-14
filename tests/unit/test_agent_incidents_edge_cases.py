from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_incidents import (
    IncidentFingerprint,
    IncidentRecord,
    IncidentStore,
    RetryDecision,
    ToolOutcome,
    _classify_error,
    _normalize_signature,
    _redact_message,
)


def test_redact_message_and_normalize_defensive_types() -> None:
    # None or non-string input
    assert _redact_message(None) == ""  # type: ignore
    assert _redact_message(12345) == "12345"  # type: ignore

    # Null bytes stripped
    assert "\x00" not in _redact_message("error \x00 with null bytes")

    # _normalize_signature
    assert _normalize_signature(None)  # type: ignore
    assert _normalize_signature("") 
    assert _normalize_signature("Error \x00 12345")


def test_classify_error_defensive() -> None:
    assert _classify_error(None, timed_out=False) == "CommandExecutionError"  # type: ignore
    assert _classify_error("busy lock error \x00", timed_out=False) == "BusyLockError"
    assert _classify_error("any error", timed_out=True) == "TimeoutError"


def test_incident_fingerprint_from_dict_and_sanitization() -> None:
    # Invalid non-mapping data
    fp_invalid = IncidentFingerprint.from_dict("invalid_data")  # type: ignore
    assert fp_invalid.error_class == "unknown"
    assert fp_invalid.operation_class == "command"

    # Null bytes and whitespace stripped
    fp = IncidentFingerprint(
        error_class=" \x00SyntaxError ",
        operation_class=" \x00tool_test ",
        signature_hash=" \x00abc123 ",
    )
    assert fp.error_class == "SyntaxError"
    assert fp.operation_class == "tool_test"
    assert fp.signature_hash == "abc123"


def test_tool_outcome_sanitization() -> None:
    outcome = ToolOutcome(
        tool_name=" \x00my_tool ",
        command=" echo \x00test ",
        error=" fail \x00msg ",
        exit_code=float("nan"),  # type: ignore
        evidence_ids=["ev-1\x00", ""],  # type: ignore
        affected_paths=["path/1\x00", ""],  # type: ignore
        metadata=None,  # type: ignore
    )
    assert outcome.tool_name == "my_tool"
    assert outcome.command == "echo test"
    assert outcome.error == "fail msg"
    assert outcome.exit_code == 0
    assert outcome.evidence_ids == ("ev-1",)
    assert outcome.affected_paths == ("path/1",)
    assert outcome.metadata == {}


def test_incident_record_helpers_and_sanitization() -> None:
    fp = IncidentFingerprint(error_class="Err", operation_class="op", signature_hash="sig")
    rec = IncidentRecord(
        incident_id=" inc-1\x00 ",
        fingerprint=fp,
        operation_class=" op\x00 ",
        error_class=" Err\x00 ",
        redacted_message=" msg\x00 ",
        state_revision=" rev-1\x00 ",
        attempts=-5,
        confidence=float("nan"),
        created_at=-10.0,
        updated_at=-5.0,
        resolved=False,
        ignored=False,
        verified_fix="fix",
    )
    assert rec.incident_id == "inc-1"
    assert rec.attempts == 1
    assert rec.confidence == 0.0
    assert rec.created_at == 0.0
    assert rec.updated_at == 0.0
    assert rec.is_resolved() is False
    assert rec.is_ignored() is False
    assert rec.is_active() is True
    assert rec.has_verified_fix() is True


def test_retry_decision_helpers() -> None:
    d1 = RetryDecision(action="apply_verified_fix", reason="known fix", verified_fix="do x")
    assert d1.can_retry() is True
    assert d1.should_stop() is False

    d2 = RetryDecision(action="stop", reason="repeated failure")
    assert d2.can_retry() is False
    assert d2.should_stop() is True


def test_incident_store_inspection_helpers(tmp_path: Path) -> None:
    store = IncidentStore(AgentStateStore(tmp_path / "state.sqlite3"))
    assert store.has_incidents() is False
    assert store.incident_count() == 0

    outcome = ToolOutcome(
        tool_name="command",
        error="some failure",
        exit_code=1,
    )
    rec = store.capture(outcome)
    assert rec is not None
    assert store.has_incidents() is True
    assert store.incident_count() == 1
    assert store.incident_count(resolved=False) == 1
    assert store.incident_count(resolved=True) == 0

    store.resolve(rec.incident_id, verified_fix="fixed")
    assert store.incident_count(resolved=True) == 1
    assert store.incident_count(resolved=False) == 0
