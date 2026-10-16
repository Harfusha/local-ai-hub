from __future__ import annotations

import math
import pytest
from local_ai_hub.agent_learning import (
    CandidateStatus,
    ImprovementCandidate,
    PromotionDecision,
    RollbackTrigger,
    SLOObservation,
)


def test_slo_observation_hardening() -> None:
    # Booleans must not coerce to 1.0 or 1
    obs = SLOObservation(latency_ms=True, cost=True, error_count=True)
    assert obs.latency_ms == 0.0
    assert obs.cost == 0.0
    assert obs.error_count == 0

    # Inf and NaN and OverflowError values must fall back safely
    obs2 = SLOObservation(latency_ms=float("inf"), cost=float("nan"), error_count=float("inf"))
    assert obs2.latency_ms == 0.0
    assert obs2.cost == 0.0
    assert obs2.error_count == 0

    # Invalid string / None fallbacks
    obs3 = SLOObservation(latency_ms="bad", cost=None, error_count="bad")
    assert obs3.latency_ms == 0.0
    assert obs3.cost == 0.0
    assert obs3.error_count == 0


def test_improvement_candidate_post_init_and_from_dict_hardening() -> None:
    # Boolean values inside slo_thresholds and metrics dicts must not coerce to 1.0
    cand = ImprovementCandidate(
        candidate_id="cand_1\x00",
        name="test\x00_cand",
        baseline_version="1.0.0",
        candidate_version="1.0.1",
        slo_thresholds={"max_latency": True, "valid_lat": 15.5},  # type: ignore[arg-type]
        metrics={"score": True, "valid_score": 0.95},  # type: ignore[arg-type]
        created_at=True,  # type: ignore[arg-type]
        updated_at=float("inf"),
    )
    assert cand.candidate_id == "cand_1"
    assert cand.name == "test_cand"
    assert cand.slo_thresholds["max_latency"] == 0.0
    assert cand.slo_thresholds["valid_lat"] == 15.5
    assert cand.metrics["score"] == 0.0
    assert cand.metrics["valid_score"] == 0.95
    assert cand.created_at == 0.0
    assert cand.updated_at == 0.0

    # from_dict with boolean or invalid slo_thresholds/metrics must not crash
    data = {
        "candidate_id": "cand_2",
        "name": "cand_two",
        "baseline_version": "1.0",
        "candidate_version": "1.1",
        "slo_thresholds": True,
        "metrics": None,
        "created_at": True,
    }
    c2 = ImprovementCandidate.from_dict(data)
    assert c2.candidate_id == "cand_2"
    assert c2.slo_thresholds == {}
    assert c2.metrics == {}
    assert c2.created_at == 0.0

    with pytest.raises(TypeError):
        ImprovementCandidate.from_dict(True)  # type: ignore[arg-type]


def test_rollback_and_promotion_decision_sanitization() -> None:
    rb = RollbackTrigger(
        candidate_id="cand\x001",
        action="rollback\x00",
        reason="breached\x00",
        restored_version="v1\x00",
    )
    assert rb.candidate_id == "cand1"
    assert rb.action == "rollback"
    assert rb.reason == "breached"
    assert rb.restored_version == "v1"

    pd = PromotionDecision(
        candidate_id="cand\x002",
        promoted=True,
        approver="user\x00",
        version="v2\x00",
    )
    assert pd.candidate_id == "cand2"
    assert pd.promoted is True
    assert pd.approver == "user"
    assert pd.version == "v2"
