from __future__ import annotations

from pathlib import Path
import pytest

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


def promoted_candidate(store: LearningStore) -> ImprovementCandidate:
    cand = store.create_candidate(valid_candidate())
    cand = store.advance(cand.candidate_id, CandidateStatus.CANARY_PASSED)
    store.promote(cand.candidate_id, approver="user")
    return store.get(cand.candidate_id)


def failing_slo_observation() -> SLOObservation:
    return SLOObservation(
        latency_ms=1200.0,  # Exceeds max_latency_ms of 500.0
        success=False,
    )


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
