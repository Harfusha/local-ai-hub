from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from pathlib import Path
import pytest

import local_ai_hub.agent_learning as agent_learning
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_learning import (
    CandidateStatus,
    ImprovementCandidate,
    LearningStore,
    RollbackTrigger,
    SLOObservation,
)
from local_ai_hub.agent_memory import ApprovalRequiredError


@pytest.fixture
def store(tmp_path: Path) -> LearningStore:
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    return LearningStore(state_store, approval_verifier=_test_approval_verifier)


def _test_approval_verifier(candidate: ImprovementCandidate, receipt: dict) -> str | None:
    if (
        receipt.get("action") == "promote"
        and receipt.get("candidate_id") == candidate.candidate_id
        and receipt.get("approval") == "trusted-test-approval"
    ):
        return "user"
    return None


def _test_approval_receipt(candidate: ImprovementCandidate) -> dict[str, str]:
    return {
        "action": "promote",
        "candidate_id": candidate.candidate_id,
        "approval": "trusted-test-approval",
    }


def valid_candidate() -> ImprovementCandidate:
    return ImprovementCandidate.create(
        name="routing_candidate",
        baseline_version="baseline",
        candidate_version="candidate",
        slo_thresholds={"max_latency_ms": 500.0, "min_success_rate": 0.9},
    )


def approved_candidate(store: LearningStore) -> ImprovementCandidate:
    candidate = store.create_candidate(valid_candidate())
    for status in (
        CandidateStatus.REPLAY_PASSED,
        CandidateStatus.SHADOW_PASSED,
        CandidateStatus.CANARY_PASSED,
        CandidateStatus.APPROVED,
    ):
        candidate = store.advance(candidate.candidate_id, status)
    return candidate


def promoted_candidate(
    store: LearningStore,
    threshold_overrides: dict[str, float] | None = None,
) -> ImprovementCandidate:
    candidate = valid_candidate()
    candidate.slo_thresholds.update(threshold_overrides or {})
    cand = store.create_candidate(candidate)
    for status in (
        CandidateStatus.REPLAY_PASSED,
        CandidateStatus.SHADOW_PASSED,
        CandidateStatus.CANARY_PASSED,
        CandidateStatus.APPROVED,
    ):
        cand = store.advance(cand.candidate_id, status)
    store.promote(cand.candidate_id, approval_receipt=_test_approval_receipt(cand))
    return store.get(cand.candidate_id)


@pytest.mark.parametrize(
    ("current_status", "new_status"),
    [
        (CandidateStatus.CANDIDATE, CandidateStatus.SHADOW_PASSED),
        (CandidateStatus.REPLAY_PASSED, CandidateStatus.CANARY_PASSED),
        (CandidateStatus.SHADOW_PASSED, CandidateStatus.APPROVED),
        (CandidateStatus.CANARY_PASSED, CandidateStatus.REPLAY_PASSED),
        (CandidateStatus.APPROVED, CandidateStatus.CANARY_PASSED),
        (CandidateStatus.ROLLED_BACK, CandidateStatus.REJECTED),
        (CandidateStatus.REJECTED, CandidateStatus.REPLAY_PASSED),
    ],
)
def test_advance_rejects_invalid_candidate_status_transitions(
    store: LearningStore,
    current_status: CandidateStatus,
    new_status: CandidateStatus,
):
    candidate = store.create_candidate(valid_candidate())
    candidate = ImprovementCandidate(
        candidate_id=candidate.candidate_id,
        name=candidate.name,
        baseline_version=candidate.baseline_version,
        candidate_version=candidate.candidate_version,
        status=current_status,
        slo_thresholds=candidate.slo_thresholds,
        metrics=candidate.metrics,
        approver=candidate.approver,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
    )
    store._save(candidate)

    with pytest.raises(ValueError, match="transition"):
        store.advance(candidate.candidate_id, new_status)


def test_advance_rejects_non_enum_status(store: LearningStore):
    candidate = store.create_candidate(valid_candidate())

    with pytest.raises(TypeError, match="CandidateStatus"):
        store.advance(candidate.candidate_id, "replay_passed")


def test_advance_rejects_direct_promotion(store: LearningStore):
    candidate = store.create_candidate(valid_candidate())

    with pytest.raises(ValueError, match="PROMOTED"):
        store.advance(candidate.candidate_id, CandidateStatus.PROMOTED)


def failing_slo_observation() -> SLOObservation:
    return SLOObservation(
        latency_ms=1200.0,  # Exceeds max_latency_ms of 500.0
        success=False,
    )


def test_cost_slo_breach_rolls_back_promoted_candidate(store: LearningStore):
    candidate = promoted_candidate(store, {"max_cost": 1.5})

    trigger = store.observe(candidate.candidate_id, SLOObservation(cost=1.6))

    assert trigger is not None
    assert "cost" in trigger.reason


def test_error_count_slo_breach_rolls_back_promoted_candidate(store: LearningStore):
    candidate = promoted_candidate(store, {"max_error_count": 0})

    trigger = store.observe(candidate.candidate_id, SLOObservation(error_count=1))

    assert trigger is not None
    assert "error count" in trigger.reason


def test_candidate_cannot_promote_without_approval(store: LearningStore):
    candidate = approved_candidate(store)
    with pytest.raises(ApprovalRequiredError):
        store.promote(candidate.candidate_id, approver="agent")


def test_approver_string_alone_does_not_authorize_promotion(store: LearningStore):
    candidate = approved_candidate(store)

    with pytest.raises(ApprovalRequiredError, match="authoritative approval receipt"):
        store.promote(candidate.candidate_id, approver="user")


def test_candidate_promotes_with_user_approval(store: LearningStore):
    candidate = approved_candidate(store)
    decision = store.promote(
        candidate.candidate_id,
        approval_receipt=_test_approval_receipt(candidate),
    )
    assert decision.promoted is True
    assert store.get(candidate.candidate_id).status is CandidateStatus.PROMOTED


def test_candidate_cannot_promote_before_approval_stage(store: LearningStore):
    candidate = store.create_candidate(valid_candidate())

    with pytest.raises(ValueError, match="APPROVED"):
        store.promote(
            candidate.candidate_id,
            approval_receipt=_test_approval_receipt(candidate),
        )


def test_candidate_promotion_rejects_mismatched_approval_receipt(store: LearningStore):
    candidate = approved_candidate(store)
    receipt = _test_approval_receipt(candidate)
    receipt["candidate_id"] = "another-candidate"

    with pytest.raises(ApprovalRequiredError, match="invalid"):
        store.promote(candidate.candidate_id, approval_receipt=receipt)


def test_candidate_promotion_rejects_missing_authoritative_verifier(tmp_path: Path):
    store = LearningStore(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    candidate = store.create_candidate(valid_candidate())
    for status in (
        CandidateStatus.REPLAY_PASSED,
        CandidateStatus.SHADOW_PASSED,
        CandidateStatus.CANARY_PASSED,
        CandidateStatus.APPROVED,
    ):
        candidate = store.advance(candidate.candidate_id, status)

    with pytest.raises(ApprovalRequiredError, match="no authoritative"):
        store.promote(
            candidate.candidate_id,
            approval_receipt=_test_approval_receipt(candidate),
        )


def _learning_event_count(store: LearningStore, candidate_id: str, kind: str) -> int:
    with closing(sqlite3.connect(store.state_store.db_path)) as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM agent_events WHERE stream_id = ? AND kind = ?",
            (f"learning:{candidate_id}", kind),
        ).fetchone()
    return int(row[0])


@pytest.mark.parametrize("failure_point", ["before_event", "after_event", "before_projection", "after_projection"])
def test_learning_transition_rolls_back_event_and_projection_on_failure(
    store: LearningStore,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
):
    candidate = store.create_candidate(valid_candidate())
    real_append = store.state_store.append_in_transaction
    real_projection = getattr(store, "_write_projection_in_transaction", None)

    if failure_point == "before_event":
        monkeypatch.setattr(
            store.state_store,
            "append_in_transaction",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("before event")),
        )
    elif failure_point == "after_event":
        def append_then_fail(*args, **kwargs):
            real_append(*args, **kwargs)
            raise RuntimeError("after event")

        monkeypatch.setattr(store.state_store, "append_in_transaction", append_then_fail)
    elif failure_point == "before_projection":
        def fail_before_projection(*_args, **_kwargs):
            raise RuntimeError("before projection")

        monkeypatch.setattr(store, "_write_projection_in_transaction", fail_before_projection, raising=False)
    else:
        assert callable(real_projection), "LearningStore must expose its transaction projection seam"

        def project_then_fail(*args, **kwargs):
            real_projection(*args, **kwargs)
            raise RuntimeError("after projection")

        monkeypatch.setattr(store, "_write_projection_in_transaction", project_then_fail, raising=False)

    with pytest.raises(RuntimeError):
        store.advance(candidate.candidate_id, CandidateStatus.REPLAY_PASSED)

    assert store.get(candidate.candidate_id).status is CandidateStatus.CANDIDATE
    assert _learning_event_count(store, candidate.candidate_id, "learning.advanced") == 0


def test_learning_transition_retry_is_idempotent(store: LearningStore):
    candidate = store.create_candidate(valid_candidate())

    first = store.advance(candidate.candidate_id, CandidateStatus.REPLAY_PASSED)
    repeated = store.advance(candidate.candidate_id, CandidateStatus.REPLAY_PASSED)

    assert first == repeated
    assert _learning_event_count(store, candidate.candidate_id, "learning.advanced") == 1


def test_slo_success_rate_uses_bounded_sliding_window(store: LearningStore):
    candidate = valid_candidate()
    candidate.slo_thresholds.update(
        {"min_success_rate": 0.5, "min_samples": 3, "window_size": 3}
    )
    store.create_candidate(candidate)
    for status in (
        CandidateStatus.REPLAY_PASSED,
        CandidateStatus.SHADOW_PASSED,
        CandidateStatus.CANARY_PASSED,
        CandidateStatus.APPROVED,
    ):
        store.advance(candidate.candidate_id, status)
    store.promote(
        candidate.candidate_id,
        approval_receipt=_test_approval_receipt(candidate),
    )

    for _ in range(3):
        assert store.observe(candidate.candidate_id, SLOObservation(success=True)) is None
    assert store.observe(candidate.candidate_id, SLOObservation(success=False)) is None
    assert store.get(candidate.candidate_id).status is CandidateStatus.PROMOTED

    trigger = store.observe(candidate.candidate_id, SLOObservation(success=False))

    assert trigger is not None
    assert "1/3" in trigger.reason
    assert store.get(candidate.candidate_id).status is CandidateStatus.ROLLED_BACK


def test_slo_window_persists_success_failure_and_minimum_sample_counts(store: LearningStore):
    candidate = valid_candidate()
    candidate.slo_thresholds.update(
        {"min_success_rate": 0.5, "min_samples": 3, "window_size": 4}
    )
    store.create_candidate(candidate)
    for status in (
        CandidateStatus.REPLAY_PASSED,
        CandidateStatus.SHADOW_PASSED,
        CandidateStatus.CANARY_PASSED,
        CandidateStatus.APPROVED,
    ):
        store.advance(candidate.candidate_id, status)
    store.promote(
        candidate.candidate_id,
        approval_receipt=_test_approval_receipt(candidate),
    )

    assert store.observe(candidate.candidate_id, SLOObservation(success=False)) is None
    assert store.observe(candidate.candidate_id, SLOObservation(success=True)) is None

    observed = store.get(candidate.candidate_id)
    assert observed.metrics["slo_window_count"] == 2.0
    assert observed.metrics["slo_window_success_count"] == 1.0
    assert observed.metrics["slo_window_failure_count"] == 1.0


def test_declared_regression_rolls_back_to_last_known_good(store: LearningStore):
    candidate = promoted_candidate(store)
    trigger = store.observe(candidate.candidate_id, failing_slo_observation())
    assert trigger is not None
    assert trigger.action == "rollback"
    assert trigger.restored_version == "baseline"
    assert store.get(candidate.candidate_id).status is CandidateStatus.ROLLED_BACK


def test_save_logs_rollback_failure_and_preserves_original_error(
    store: LearningStore, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    real_connect = agent_learning.connect_sqlite

    class RollbackFailingConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, statement, *args, **kwargs):
            normalized = " ".join(statement.split()).upper()
            if normalized.startswith("INSERT INTO AGENT_LEARNING_CANDIDATES"):
                raise ValueError("candidate insert failed")
            if normalized == "ROLLBACK":
                raise sqlite3.OperationalError("rollback failed")
            return self.connection.execute(statement, *args, **kwargs)

        def close(self):
            self.connection.close()

    monkeypatch.setattr(
        agent_learning,
        "connect_sqlite",
        lambda *args, **kwargs: RollbackFailingConnection(real_connect(*args, **kwargs)),
    )

    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError, match="candidate insert failed"):
            store._save(valid_candidate())

    assert any(
        record.name == agent_learning.__name__
        and "learning rollback failed" in record.getMessage()
        and "OperationalError" in record.getMessage()
        for record in caplog.records
    )
