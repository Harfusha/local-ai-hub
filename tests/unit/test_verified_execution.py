from __future__ import annotations

import pytest

from local_ai_hub.agent_task_models import GoalContract
from local_ai_hub.verified_execution import execution_projection, normalize_execution


def _project(*, satisfied=(), unsatisfied=(), stale=(), blockers=(), complete=False):
    return execution_projection(
        ("api", "consumer", "docs"),
        {"profile": "implementation", "units": {
            "api": {"dimension": "contract"},
            "consumer": {"dimension": "integration", "depends_on": ["api"], "priority": 90},
            "docs": {"dimension": "documentation"},
        }},
        satisfied=satisfied, unsatisfied=unsatisfied, stale=stale,
        receipt_ids={"consumer": "receipt-consumer", "api": "receipt-api"},
        receipt_gate_complete=complete, blockers=blockers,
    )


def test_contract_round_trip_and_no_aliasing():
    raw = {"verified_execution": {"units": {"b": {"depends_on": ["a"]}}}}
    contract = GoalContract("implement", acceptance_criteria=("a", "b"), slo_profile=raw)
    raw["verified_execution"]["units"]["b"]["depends_on"].clear()
    restored = GoalContract.from_dict(contract.to_dict())
    assert restored == contract
    assert restored.slo_profile["verified_execution"]["units"]["b"]["depends_on"] == ["a"]


@pytest.mark.parametrize("config", [
    {"units": {"a": {"depends_on": ["b"]}, "b": {"depends_on": ["a"]}}},
    {"units": {"a": {"depends_on": ["missing"]}}},
    {"units": {"a": {"priority": True}}},
    {"units": {"a": {"depends_on": ["a"]}}},
    {"units": {"missing": {}}},
    {"required_dimensions": ["security"]},
    {"version": True},
    {"units": {"a": {"status": "verified"}}},
])
def test_reject_invalid_contract_graph(config):
    with pytest.raises(ValueError):
        normalize_execution(("a", "b"), config)


def test_reject_duplicate_or_empty_criteria():
    for criteria in ((), ("a", "a")):
        with pytest.raises(ValueError):
            normalize_execution(criteria, {})


def test_stale_prerequisite_invalidates_dependent_coverage():
    result = _project(satisfied=("consumer",), stale=("api",), unsatisfied=("docs",))
    assert result["coverage"] == {
        "total": 3, "verified": 0, "unverified": 1, "stale": 1, "dependency_blocked": 1,
    }
    assert result["next_obligation"]["criterion"] == "api"
    assert not result["ready_for_completion_attempt"]


def test_no_receipt_id_can_fake_verification():
    result = _project(unsatisfied=("api", "consumer", "docs"))
    assert result["coverage"]["verified"] == 0
    assert result["next_obligation"]["criterion"] == "api"
    assert "verified_receipt_id" not in result["next_obligation"]


def test_project_obligation_and_checkpoint_blockers():
    result = _project(satisfied=("api", "consumer", "docs"), unsatisfied=("lint",))
    assert result["dimensions"]["project_verification"] == {"total": 1, "verified": 0}
    assert result["next_obligation"]["criterion"] == "lint"
    blocked = _project(satisfied=("api", "consumer", "docs"), complete=True, blockers=("investigate",))
    assert blocked["receipt_gate_complete"] is True
    assert blocked["ready_for_completion_attempt"] is False
    assert blocked["checkpoint_blocker_count"] == 1


def test_all_obligations_verified():
    result = _project(satisfied=("api", "consumer", "docs"), complete=True)
    assert result["coverage"]["verified"] == 3
    assert result["ready_for_completion_attempt"] is True
    assert result["next_obligation"] is None


def test_preview_is_bounded_and_counts_are_not_truncated():
    criteria = tuple(f"check-{i:04}" for i in range(100))
    result = execution_projection(
        criteria, {}, satisfied=(), unsatisfied=criteria, stale=(),
        receipt_ids={}, receipt_gate_complete=False,
    )
    assert result["remaining_count"] == 100
    assert len(result["remaining_preview"]) == 12
    assert result["preview_truncated"] is True


def test_additive_steering_inherits_mandatory_independent_unit():
    raw = normalize_execution(("a",), {"units": {"a": {"dimension": "audit"}}})
    result = execution_projection(
        ("a", "new-obligation"), raw, satisfied=("a",), unsatisfied=("new-obligation",),
        stale=(), receipt_ids={"a": "r"}, receipt_gate_complete=False,
    )
    assert result["next_obligation"]["criterion"] == "new-obligation"
    assert result["coverage"]["total"] == 2
