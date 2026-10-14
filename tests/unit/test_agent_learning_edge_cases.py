from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_learning import (
    CandidateStatus,
    ImprovementCandidate,
    LearningStore,
    PromotionDecision,
    RollbackTrigger,
    SLOObservation,
)


def test_slo_observation_validation_and_helpers() -> None:
    obs = SLOObservation(
        latency_ms=float("nan"),  # type: ignore
        success=True,
        cost=-10.0,
        error_count=-5,
    )
    assert obs.latency_ms == 0.0
    assert obs.cost == 0.0
    assert obs.error_count == 0
    assert obs.is_successful() is True

    failing = SLOObservation(latency_ms=10.0, success=False, error_count=1)
    assert failing.is_successful() is False


def test_rollback_trigger_and_promotion_decision_sanitization() -> None:
    rb = RollbackTrigger(
        candidate_id=" cand-1\x00 ",
        action=" rollback\x00 ",
        reason=" reason\x00 ",
        restored_version=" v1\x00 ",
    )
    assert rb.candidate_id == "cand-1"
    assert rb.action == "rollback"
    assert rb.reason == "reason"
    assert rb.restored_version == "v1"

    pd = PromotionDecision(
        candidate_id=" cand-2\x00 ",
        promoted=True,
        approver=" user\x00 ",
        version=" v2\x00 ",
    )
    assert pd.candidate_id == "cand-2"
    assert pd.approver == "user"
    assert pd.version == "v2"


def test_improvement_candidate_validation_and_helpers() -> None:
    cand = ImprovementCandidate(
        candidate_id=" cand-1\x00 ",
        name=" candidate\x00 ",
        baseline_version=" base\x00 ",
        candidate_version=" v1\x00 ",
        status=CandidateStatus.CANDIDATE,
        slo_thresholds={"max_latency_ms": float("nan"), "min_success_rate": 0.95},
        metrics={"latency": float("inf"), "cost": 0.05},
        approver=" user\x00 ",
        created_at=-10.0,
        updated_at=-5.0,
    )
    assert cand.candidate_id == "cand-1"
    assert cand.name == "candidate"
    assert cand.baseline_version == "base"
    assert cand.candidate_version == "v1"
    assert cand.approver == "user"
    assert cand.slo_thresholds["max_latency_ms"] == 0.0
    assert cand.slo_thresholds["min_success_rate"] == 0.95
    assert cand.metrics["latency"] == 0.0
    assert cand.metrics["cost"] == 0.05
    assert cand.created_at == 0.0
    assert cand.updated_at == 0.0

    # Helpers
    assert cand.is_promoted() is False
    assert cand.is_terminal() is False
    assert cand.can_advance() is True

    # from_dict validation
    with pytest.raises(TypeError):
        ImprovementCandidate.from_dict("invalid")  # type: ignore

    # from_dict invalid status fallback
    cand_dict = cand.to_dict()
    cand_dict["status"] = "unknown_status"
    recovered = ImprovementCandidate.from_dict(cand_dict)
    assert recovered.status == CandidateStatus.CANDIDATE


def test_learning_store_inspection_helpers(tmp_path: Path) -> None:
    store = LearningStore(AgentStateStore(tmp_path / "state.sqlite3"))
    assert store.has_candidates() is False
    assert store.candidate_count() == 0

    c = ImprovementCandidate.create(
        name="test_cand",
        baseline_version="v0",
        candidate_version="v1",
    )
    store.create_candidate(c)
    assert store.has_candidates() is True
    assert store.candidate_count() == 1
    assert store.candidate_count(status=CandidateStatus.CANDIDATE) == 1
    assert store.candidate_count(status=CandidateStatus.PROMOTED) == 0
