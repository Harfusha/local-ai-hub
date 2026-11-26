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
