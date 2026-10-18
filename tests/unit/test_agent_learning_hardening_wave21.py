from __future__ import annotations

import math
import pytest
from local_ai_hub.agent_learning import (
    CandidateStatus,
    ImprovementCandidate,
    LearningStore,
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
        candidate_id="cand_1",
        name="test_cand",
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

    # Persisted records are canonical inputs. Invalid fields must be rejected
    # instead of being silently converted into plausible candidate state.
    data = {
        "candidate_id": "cand_2",
        "name": "cand_two",
        "baseline_version": "1.0",
        "candidate_version": "1.1",
        "status": "candidate",
        "slo_thresholds": {},
        "metrics": {},
        "approver": "",
        "created_at": 1.0,
        "updated_at": 1.0,
    }
    assert ImprovementCandidate.from_dict(data).candidate_id == "cand_2"

    invalid_records = (
        ({**data, "status": "unknown"}, ValueError),
        ({**data, "status": True}, TypeError),
        ({**data, "slo_thresholds": True}, TypeError),
        ({**data, "metrics": None}, TypeError),
        ({**data, "metrics": {"score": True}}, TypeError),
        ({**data, "metrics": {"score": float("inf")}}, ValueError),
        ({**data, "created_at": True}, TypeError),
        ({**data, "updated_at": float("nan")}, ValueError),
        ({key: value for key, value in data.items() if key != "status"}, ValueError),
        ({**data, "created_at": 10**10000}, ValueError),
    )
    for invalid_data, error in invalid_records:
        with pytest.raises(error):
            ImprovementCandidate.from_dict(invalid_data)


def test_learning_store_rejects_corrupt_rows_and_round_trips_valid_rows() -> None:
    store = object.__new__(LearningStore)
    valid_row = (
        "cand_3",
        "candidate_three",
        "1.0",
        "1.1",
        "candidate",
        '{"max_latency": 20.0}',
        '{"score": 0.95}',
        "",
        1.0,
        2.0,
    )
    restored = store._row_to_candidate(valid_row)
    assert restored.to_dict() == {
        "candidate_id": "cand_3",
        "name": "candidate_three",
        "baseline_version": "1.0",
        "candidate_version": "1.1",
        "status": CandidateStatus.CANDIDATE.value,
        "slo_thresholds": {"max_latency": 20.0},
        "metrics": {"score": 0.95},
        "approver": "",
        "created_at": 1.0,
        "updated_at": 2.0,
    }

    invalid_rows = (
        (*valid_row[:4], "unknown", *valid_row[5:]),
        (*valid_row[:5], "{", *valid_row[6:]),
        (*valid_row[:5], "[]", *valid_row[6:]),
        (*valid_row[:6], '{"score": true}', *valid_row[7:]),
        (*valid_row[:8], True, valid_row[9]),
    )
    for invalid_row in invalid_rows:
        with pytest.raises((TypeError, ValueError)):
            store._row_to_candidate(invalid_row)

    with pytest.raises(TypeError):
        ImprovementCandidate.from_dict(True)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value", "error"),
    (
        ("candidate_id", True, TypeError),
        ("name", 7, TypeError),
        ("baseline_version", None, TypeError),
        ("candidate_version", "", ValueError),
        ("candidate_id", "candidate\x00id", ValueError),
        ("candidate_id", "", ValueError),
        ("name", " candidate", ValueError),
        ("status", CandidateStatus.CANDIDATE.value, TypeError),
        ("status", "unknown", TypeError),
        ("status", True, TypeError),
        ("approver", "operator\x00", ValueError),
        ("approver", False, TypeError),
        ("metrics", True, TypeError),
        ("slo_thresholds", {1: 0.5}, TypeError),
    ),
)
def test_improvement_candidate_rejects_noncanonical_direct_inputs(field, value, error) -> None:
    data = {
        "candidate_id": "candidate_1",
        "name": "candidate one",
        "baseline_version": "1.0",
        "candidate_version": "1.1",
        "status": CandidateStatus.CANDIDATE,
        "slo_thresholds": {},
        "metrics": {},
        "approver": "",
        "created_at": 1.0,
        "updated_at": 1.0,
    }
    data[field] = value

    with pytest.raises(error):
        ImprovementCandidate(**data)


@pytest.mark.parametrize("field", ("slo_thresholds", "metrics"))
def test_improvement_candidate_create_rejects_non_mapping_metrics(field) -> None:
    values = {field: False}

    with pytest.raises(TypeError):
        ImprovementCandidate.create("candidate", "1.0", "1.1", **values)


def test_rollback_and_promotion_decision_canonical_text() -> None:
    rb = RollbackTrigger(
        candidate_id="cand1",
        action="rollback",
        reason="breached",
        restored_version="v1",
    )
    assert rb.candidate_id == "cand1"
    assert rb.action == "rollback"
    assert rb.reason == "breached"
    assert rb.restored_version == "v1"

    pd = PromotionDecision(
        candidate_id="cand2",
        promoted=True,
        approver="user",
        version="v2",
    )
    assert pd.candidate_id == "cand2"
    assert pd.promoted is True
    assert pd.approver == "user"
    assert pd.version == "v2"
