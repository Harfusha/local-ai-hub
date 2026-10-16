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


def test_verification_receipt_helpers_require_canonical_strings() -> None:
    rcpt = VerificationReceipt(
        receipt_id="rcpt-1",
        task_id="task-1",
        criterion="tests",
        evidence_type="test",
        passed=True,
        evidence_id="ev-1",
        command_id="cmd-1",
        owner="owner-1",
        repository_revision="rev-1",
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
    with pytest.raises(ValueError, match="canonical string"):
        VerificationReceipt(
            receipt_id="bad\x00id", task_id="task-1", criterion="tests", observed_at=100.0,
        )

    # Helpers
    assert rcpt.is_test() is True
    assert rcpt.is_benchmark() is False
    assert rcpt.is_source_review() is False
    assert rcpt.is_expired(now=150.0) is False
    assert rcpt.is_expired(now=250.0) is True


def test_change_intent_preserves_canonical_values() -> None:
    ci = ChangeIntent.create(
        task_id="task-1",
        affected_paths=["path/a.py", "path/b.py"],
        affected_symbols=["sym_a"],
    )
    assert ci.task_id == "task-1"
    assert ci.affected_paths == ("path/a.py", "path/b.py")
    assert ci.affected_symbols == ("sym_a",)
    assert ci.created_at > 0.0

    # from_dict with non-mapping
    with pytest.raises(TypeError):
        ChangeIntent.from_dict("invalid")  # type: ignore


@pytest.mark.parametrize("field,value", [
    ("change_id", 1), ("task_id", " task-1"), ("task_id", "task\x00-1"),
    ("affected_paths", "path.py"), ("affected_paths", None),
    ("affected_paths", [1]), ("affected_paths", ["bad\x00.py"]),
    ("affected_symbols", "symbol"), ("affected_symbols", [None]),
    ("expected_impact", None), ("rollback_description", 1),
    ("created_at", True), ("created_at", "10"), ("created_at", -1),
    ("created_at", float("nan")), ("created_at", float("inf")), ("created_at", 10 ** 1000),
])
def test_change_intent_rejects_coercive_fields(field, value) -> None:
    payload = ChangeIntent.create("task-1", ["path.py"]).to_dict()
    payload[field] = value
    with pytest.raises((TypeError, ValueError)):
        ChangeIntent.from_dict(payload)


def test_change_intent_factory_preserves_paths_and_requires_collection_and_time() -> None:
    intent = ChangeIntent.create("task-1", [" spaced path.py "], expected_impact="  text  ")
    assert intent.affected_paths == (" spaced path.py ",)
    assert intent.expected_impact == "  text  "
    with pytest.raises(TypeError):
        ChangeIntent.create("task-1", "path.py")
    payload = intent.to_dict()
    del payload["created_at"]
    with pytest.raises(KeyError):
        ChangeIntent.from_dict(payload)


def test_outcome_record_helpers_preserve_canonical_identity() -> None:
    out = OutcomeRecord.accepted("chg-1", task_id="task-1", actor="admin")
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


@pytest.mark.parametrize("field,value", [
    ("outcome_id", 1), ("outcome_id", ""), ("change_id", "chg\x00-1"),
    ("task_id", " task-1"), ("actor", ""), ("actor", None),
    ("kind", ""), ("kind", None), ("kind", "Accepted"), ("kind", "unknown"),
    ("created_at", True), ("created_at", "10"), ("created_at", -1),
    ("created_at", float("nan")), ("created_at", float("inf")),
    ("created_at", 10 ** 1000),
    ("details", []), ("details", None),
])
def test_outcome_record_rejects_coercive_or_fabricated_fields(field, value) -> None:
    payload = OutcomeRecord.accepted("chg-1").to_dict()
    payload[field] = value
    with pytest.raises((TypeError, ValueError)):
        OutcomeRecord.from_dict(payload)


def test_outcome_record_requires_explicit_kind_and_factory_validates_inputs() -> None:
    with pytest.raises(TypeError):
        OutcomeRecord(outcome_id="out-1")
    with pytest.raises(KeyError):
        OutcomeRecord.from_dict({"outcome_id": "out-1"})
    with pytest.raises(ValueError, match="canonical string"):
        OutcomeRecord.accepted("chg-1\x00")
    with pytest.raises(TypeError, match="mapping"):
        OutcomeRecord.accepted("chg-1", details=[])
    assert OutcomeRecord.accepted("chg-1", details=None).details == {}


@pytest.mark.parametrize("field", ["kind", "actor", "created_at"])
def test_outcome_deserialization_requires_outcome_provenance(field) -> None:
    payload = OutcomeRecord.accepted("chg-1").to_dict()
    del payload[field]
    with pytest.raises(KeyError):
        OutcomeRecord.from_dict(payload)


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
        task_id="task-1",
        complete=False,
        satisfied_criteria=("crit-1",),
        unsatisfied_criteria=("crit-2",),
        stale_criteria=("crit-3",),
        receipts=(rcpt,),
    )
    assert res.task_id == "task-1"
    assert res.is_complete() is False
    assert res.has_receipts() is True
    assert res.receipt_count() == 1
    assert res.satisfied_count() == 1
    assert res.unsatisfied_count() == 1
    assert res.stale_count() == 1
    assert res.all_criteria() == ("crit-1", "crit-2", "crit-3")


@pytest.mark.parametrize("field,value", [
    ("task_id", 1), ("task_id", " task-1"), ("task_id", "task\x00-1"),
    ("complete", 1), ("complete", "true"), ("complete", None),
    ("satisfied_criteria", "criterion"), ("unsatisfied_criteria", None),
    ("stale_criteria", [1]), ("satisfied_criteria", ["bad\x00"]),
    ("satisfied_criteria", [" padded "]), ("satisfied_criteria", [""]),
    ("receipts", None), ("receipts", [object()]),
    ("consistency", []), ("consistency", None),
])
def test_completion_result_rejects_coercive_fields(field, value) -> None:
    payload = dict(task_id="task-1", complete=False, satisfied_criteria=(),
                   unsatisfied_criteria=(), stale_criteria=(), receipts=(), consistency={})
    payload[field] = value
    with pytest.raises((TypeError, ValueError)):
        CompletionResult(**payload)


@pytest.mark.parametrize("field", ["unsatisfied_criteria", "stale_criteria"])
def test_completion_result_rejects_contradictory_success(field) -> None:
    payload = dict(task_id="task-1", complete=True, satisfied_criteria=(),
                   unsatisfied_criteria=(), stale_criteria=(), receipts=())
    payload[field] = ("criterion",)
    with pytest.raises(ValueError, match="complete cannot be true"):
        CompletionResult(**payload)


def test_completion_result_rejects_success_without_criteria() -> None:
    with pytest.raises(ValueError, match="at least one satisfied criterion"):
        CompletionResult(task_id="task-1", complete=True, satisfied_criteria=(),
                         unsatisfied_criteria=(), stale_criteria=(), receipts=())


@pytest.mark.parametrize("receipt_fields", [
    None, {"task_id": "other-task"}, {"passed": False}, {"evidence_id": ""},
    {"criterion": "other-criterion"},
])
def test_completion_result_requires_matching_successful_receipts(receipt_fields) -> None:
    receipts = ()
    if receipt_fields is not None:
        fields = dict(receipt_id="rcpt-1", task_id="task-1", criterion="criterion",
                      passed=True, evidence_id="evidence-1")
        fields.update(receipt_fields)
        receipts = (VerificationReceipt(**fields),)
    with pytest.raises(ValueError, match="passing evidence receipts"):
        CompletionResult(task_id="task-1", complete=True, satisfied_criteria=("criterion",),
                         unsatisfied_criteria=(), stale_criteria=(), receipts=receipts)


def test_completion_result_accepts_structurally_backed_success() -> None:
    receipt = VerificationReceipt(receipt_id="rcpt-1", task_id="task-1", criterion="criterion",
                                  passed=True, evidence_id="evidence-1")
    result = CompletionResult(task_id="task-1", complete=True, satisfied_criteria=("criterion",),
                              unsatisfied_criteria=(), stale_criteria=(), receipts=(receipt,))
    assert result.complete is True


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
