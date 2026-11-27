from types import SimpleNamespace

import pytest

from local_ai_hub.execution_problems import project_problems, record_problem


def test_report_lifecycle_is_derived_from_new_valid_receipt():
    report = {"id": "issue", "title": "contradiction", "criterion": "review"}
    state = record_problem({}, report, criteria=("review",), receipt_ids={"review": "old"}, reporter="agent", now=10)
    old = SimpleNamespace(receipt_id="old", observed_at=11)
    assert project_problems(state, satisfied=("review",), receipts={"review": old})["blocking_open"] == 1
    preexisting = SimpleNamespace(receipt_id="different", observed_at=9)
    assert project_problems(state, satisfied=("review",), receipts={"review": preexisting})["blocking_open"] == 1
    fresh = SimpleNamespace(receipt_id="new", observed_at=12)
    assert project_problems(state, satisfied=("review",), receipts={"review": fresh})["resolved"] == 1
    assert project_problems(state, satisfied=(), receipts={"review": fresh})["blocking_open"] == 1
    replay = record_problem(state, report, criteria=("review",), receipt_ids={"review": "new"}, reporter="agent", now=20)
    assert replay == state


def test_nonblocking_report_without_criterion_remains_visible():
    state = record_problem({}, {"id": "issue", "title": "possible issue", "blocking": False},
                           criteria=(), receipt_ids={}, reporter="agent", now=10)
    result = project_problems(state, satisfied=(), receipts={})
    assert result["open"] == 1
    assert result["blocking_open"] == 0


def test_reject_unverified_agent_resolution_flag():
    with pytest.raises(ValueError):
        record_problem({}, {"id": "issue", "title": "issue", "criterion": "review", "resolved": True},
                       criteria=("review",), receipt_ids={}, reporter="agent", now=10)


def test_confirmation_requires_distinct_fresh_evidence_after_primary():
    report = {"id": "issue", "title": "mismatch", "criterion": "repair",
              "resolution_criterion": "verify"}
    state = record_problem({}, report, criteria=("repair", "verify"), receipt_ids={},
                           reporter="agent", now=10)

    def proof(receipt_id, evidence_id, observed_at):
        return SimpleNamespace(receipt_id=receipt_id, evidence_id=evidence_id, observed_at=observed_at)

    primary = proof("repair-id", "repair-evidence", 12)
    result = project_problems(state, satisfied=("repair",), receipts={"repair": primary})
    assert result["blocking_criteria"] == ["verify"]
    assert result["open_preview"][0]["resolution_status"] == "awaiting_confirmation"
    for invalid in (
        proof("verify-id", "verify-evidence", 11),
        proof("verify-id", "repair-evidence", 13),
        proof("repair-id", "verify-evidence", 13),
    ):
        result = project_problems(state, satisfied=("repair", "verify"),
                                  receipts={"repair": primary, "verify": invalid})
        assert result["blocking_open"] == 1
    confirmation = proof("verify-id", "verify-evidence", 13)
    assert project_problems(state, satisfied=("repair", "verify"),
                            receipts={"repair": primary, "verify": confirmation})["resolved"] == 1
    assert project_problems(state, satisfied=("repair",),
                            receipts={"repair": primary, "verify": confirmation})["blocking_open"] == 1


@pytest.mark.parametrize("resolution", ["repair", "missing", "", None])
def test_reject_invalid_resolution_criterion(resolution):
    with pytest.raises(ValueError, match="resolution criterion"):
        record_problem({}, {"id": "issue", "title": "mismatch", "criterion": "repair",
                            "resolution_criterion": resolution},
                       criteria=("repair", "verify"), receipt_ids={}, reporter="agent", now=10)


def test_reject_confirmation_that_is_transitive_prerequisite_of_primary():
    from local_ai_hub.execution_problems import validate_resolution_order

    config = {"units": {"repair": {"depends_on": ["middle"]},
                        "middle": {"depends_on": ["verify"]}}}
    with pytest.raises(ValueError, match="prerequisite"):
        validate_resolution_order({"criterion": "repair", "resolution_criterion": "verify"}, config)
    validate_resolution_order({"criterion": "verify", "resolution_criterion": "repair"}, config)
