from __future__ import annotations

import logging
import sqlite3
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
    return LearningStore(state_store)


def valid_candidate() -> ImprovementCandidate:
    return ImprovementCandidate.create(
        name="routing_candidate",
        baseline_version="baseline",
        candidate_version="candidate",
        slo_thresholds={"max_latency_ms": 500.0, "min_success_rate": 0.9},
    )


def promoted_candidate(
    store: LearningStore,
    threshold_overrides: dict[str, float] | None = None,
) -> ImprovementCandidate:
    candidate = valid_candidate()
    candidate.slo_thresholds.update(threshold_overrides or {})
    cand = store.create_candidate(candidate)
    cand = store.advance(cand.candidate_id, CandidateStatus.CANARY_PASSED)
    store.promote(cand.candidate_id, approver="user")
    return store.get(cand.candidate_id)


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
    candidate = store.create_candidate(valid_candidate())
    with pytest.raises(ApprovalRequiredError):
        store.promote(candidate.candidate_id, approver="agent")


def test_candidate_promotes_with_user_approval(store: LearningStore):
    candidate = store.create_candidate(valid_candidate())
    decision = store.promote(candidate.candidate_id, approver="user")
    assert decision.promoted is True
    assert store.get(candidate.candidate_id).status is CandidateStatus.PROMOTED


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
