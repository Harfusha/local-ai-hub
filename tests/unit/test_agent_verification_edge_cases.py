from __future__ import annotations

import math
from typing import Any

import pytest

from local_ai_hub.agent_verification import (
    ChangeIntent,
    CompletionResult,
    OutcomeRecord,
    VerificationReceipt,
    classify_verification_command,
    criterion_evidence_type,
)


def test_verification_receipt_helpers_and_sanitization() -> None:
    rcpt = VerificationReceipt(
        receipt_id=" rcpt-1\x00 ",
        task_id=" task-1\x00 ",
        criterion=" tests\x00 ",
        evidence_type="test",
        passed=True,
        evidence_id=" ev-1\x00 ",
        command_id=" cmd-1\x00 ",
        owner=" owner-1\x00 ",
        repository_revision=" rev-1\x00 ",
        mutation_generation=0,
        observed_at=100.0,
        expires_at=200.0,
    )
    assert rcpt.receipt_id == "rcpt-1"
    assert rcpt.task_id == "task-1"
    assert rcpt.criterion == "tests"
    assert rcpt.evidence_id == "ev-1"
    assert rcpt.command_id == "cmd-1"
    assert rcpt.owner == "owner-1"
    assert rcpt.repository_revision == "rev-1"

    # Helpers
    assert rcpt.is_test() is True
    assert rcpt.is_benchmark() is False
    assert rcpt.is_source_review() is False
    assert rcpt.is_expired(now=150.0) is False
    assert rcpt.is_expired(now=250.0) is True


def test_change_intent_sanitization() -> None:
    ci = ChangeIntent.create(
        task_id="task-1\x00",
        affected_paths=["path/a.py\x00", "path/b.py "],
        affected_symbols=["sym_a\x00"],
    )
    assert ci.task_id == "task-1"
    assert ci.affected_paths == ("path/a.py", "path/b.py")
    assert ci.affected_symbols == ("sym_a",)
    assert ci.created_at > 0.0

    # from_dict with non-mapping
    with pytest.raises(TypeError):
        ChangeIntent.from_dict("invalid")  # type: ignore


def test_outcome_record_helpers_and_sanitization() -> None:
    out = OutcomeRecord.accepted("chg-1\x00", task_id="task-1\x00", actor="admin\x00")
    assert out.change_id == "chg-1"
    assert out.task_id == "task-1"
    assert out.actor == "admin"
    assert out.is_accepted() is True
    assert out.is_reverted() is False
    assert out.is_corrected() is False
    assert out.is_regressed() is False
    assert out.is_rejected() is False

    rev = OutcomeRecord.reverted("chg-2")
    assert rev.is_reverted() is True

    cor = OutcomeRecord.corrected("chg-3")
    assert cor.is_corrected() is True

    reg = OutcomeRecord.regressed("chg-4")
    assert reg.is_regressed() is True

    rej = OutcomeRecord.rejected("chg-5")
    assert rej.is_rejected() is True

    # from_dict with non-mapping
    with pytest.raises(TypeError):
        OutcomeRecord.from_dict("invalid")  # type: ignore


def test_completion_result_helpers() -> None:
    rcpt = VerificationReceipt(
        receipt_id="rcpt-1",
        task_id="task-1",
        criterion="unit tests",
        evidence_type="test",
        passed=True,
        evidence_id="ev-1",
        command_id="cmd-1",
    )
    res = CompletionResult(
        task_id=" task-1\x00 ",
        complete=True,
        satisfied_criteria=("crit-1\x00",),
        unsatisfied_criteria=("crit-2",),
        stale_criteria=("crit-3",),
        receipts=(rcpt,),
    )
    assert res.task_id == "task-1"
    assert res.is_complete() is True
    assert res.has_receipts() is True
    assert res.receipt_count() == 1
    assert res.satisfied_count() == 1
    assert res.unsatisfied_count() == 1
    assert res.stale_count() == 1
    assert res.all_criteria() == ("crit-1", "crit-2", "crit-3")


def test_criterion_evidence_type_defensive() -> None:
    assert criterion_evidence_type(None) == "source_review"  # type: ignore
    assert criterion_evidence_type("benchmark latency") == "benchmark"
    assert criterion_evidence_type("run unit tests \x00") == "test"
    assert criterion_evidence_type("") == "source_review"


def test_classify_verification_command_defensive() -> None:
    assert classify_verification_command(None) == "source_review"  # type: ignore
    assert classify_verification_command("pytest -q \x00") == "test"
    assert classify_verification_command("hyperfine 'sleep 1'") == "benchmark"
    assert classify_verification_command("git status") == "source_review"
