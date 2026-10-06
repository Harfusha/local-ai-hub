from __future__ import annotations

import json
from collections import UserDict
from contextlib import closing
from dataclasses import replace

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import (
    ConcurrentTaskUpdateError,
    GoalContract,
    TaskStore,
)
from local_ai_hub.agent_verification import (
    ChangeIntent,
    VerificationReceipt,
    VerificationStore,
)
from local_ai_hub.sqlite_support import connect_sqlite


def receipt_payload():
    return {
        "receipt_id": "rcpt-input",
        "task_id": "task-input",
        "criterion": "source review",
        "passed": True,
        "evidence_id": "ev-input",
    }


@pytest.mark.parametrize("passed", [True, False])
@pytest.mark.parametrize("generation", [0, 1, 42])
@pytest.mark.parametrize("details", [{}, {"nested": {"count": 1}}])
def test_receipt_from_dict_accepts_valid_json(passed, generation, details):
    payload = receipt_payload()
    payload.update(passed=passed, mutation_generation=generation, details=details)
    receipt = VerificationReceipt.from_dict(json.loads(json.dumps(payload)))
    assert receipt.passed is passed
    assert type(receipt.mutation_generation) is int
    assert receipt.mutation_generation == generation
    assert receipt.details == details


def test_receipt_from_dict_defaults_missing_optional_fields():
    receipt = VerificationReceipt.from_dict(receipt_payload())
    assert receipt.mutation_generation == 0
    assert receipt.details == {}


def test_receipt_from_dict_accepts_mapping_details_without_aliasing():
    details = UserDict({"count": 1})
    payload = receipt_payload()
    payload["details"] = details
    receipt = VerificationReceipt.from_dict(payload)
    details["count"] = 2
    assert receipt.details == {"count": 1}


@pytest.mark.parametrize("value", [None, 0, 1, 0.0, "true", "false", [], {}])
def test_receipt_from_dict_rejects_non_boolean_json_passed(value):
    payload = receipt_payload()
    payload["passed"] = value
    with pytest.raises(ValueError, match="passed"):
        VerificationReceipt.from_dict(json.loads(json.dumps(payload)))


def test_receipt_from_dict_rejects_missing_passed():
    payload = receipt_payload()
    del payload["passed"]
    with pytest.raises(ValueError, match="passed"):
        VerificationReceipt.from_dict(payload)


@pytest.mark.parametrize("value", [None, True, False, -1, "0", "1", 0.0, 1.5, [], {}, ""])
def test_receipt_from_dict_rejects_invalid_json_generation(value):
    payload = receipt_payload()
    payload["mutation_generation"] = value
    with pytest.raises(ValueError, match="mutation_generation"):
        VerificationReceipt.from_dict(json.loads(json.dumps(payload)))


@pytest.mark.parametrize("value", [None, False, True, 0, "", "text", [], [["key", 1]]])
def test_receipt_from_dict_rejects_non_mapping_json_details(value):
    payload = receipt_payload()
    payload["details"] = value
    with pytest.raises(ValueError, match="details"):
        VerificationReceipt.from_dict(json.loads(json.dumps(payload)))


@pytest.mark.parametrize("field,value", [("passed", 1), ("mutation_generation", -1), ("details", None)])
def test_receipt_from_dict_rejects_before_construction(field, value):
    class ConstructionGuardReceipt(VerificationReceipt):
        def __init__(self, **kwargs):
            raise AssertionError("invalid payload reached receipt construction")

    payload = receipt_payload()
    payload[field] = value
    with pytest.raises(ValueError, match=field):
        ConstructionGuardReceipt.from_dict(payload)


@pytest.fixture
def change_store(tmp_path):
    state = AgentStateStore(tmp_path / "state.sqlite3")
    tasks = TaskStore(state)
    tasks.create(
        GoalContract(goal="checkpoint change", acceptance_criteria=("review",)),
        ScopeContext(task_id="change-task"),
        task_id="change-task",
    )
    return state, tasks, VerificationStore(state, task_store=tasks)


@pytest.mark.parametrize("error", [OSError("checkpoint unavailable"), ValueError("checkpoint invalid"), ConcurrentTaskUpdateError("checkpoint fenced")])
def test_record_change_propagates_unexpected_checkpoint_errors(change_store, monkeypatch, error):
    state, tasks, verifier = change_store

    def fail_checkpoint(*args, **kwargs):
        raise error

    monkeypatch.setattr(tasks, "checkpoint", fail_checkpoint)
    change = ChangeIntent.create("change-task", ["src/example.py"])
    with pytest.raises(type(error), match=str(error)):
        verifier.record_change(change)
    # Existing event/projection transaction commits before the task checkpoint.
    assert len(state.events(stream_id="change:change-task")) == 1
    with closing(connect_sqlite(state.db_path)) as con:
        assert con.execute("SELECT COUNT(*) FROM agent_change_intents").fetchone()[0] == 1


def test_record_change_tolerates_task_disappearing_before_checkpoint(change_store, monkeypatch):
    state, tasks, verifier = change_store

    def missing_checkpoint(*args, **kwargs):
        raise KeyError("task disappeared")

    monkeypatch.setattr(tasks, "checkpoint", missing_checkpoint)
    change = ChangeIntent.create("change-task", ["src/example.py"])
    assert verifier.record_change(change) is change
    assert len(state.events(stream_id="change:change-task")) == 1


def test_record_change_preserves_atomic_collision_and_checkpoint_generation(change_store):
    state, tasks, verifier = change_store
    change = ChangeIntent.create("change-task", ["src/example.py"])
    verifier.record_change(change)
    before = tasks.get("change-task").checkpoint
    assert before.state_data["mutation_generation"] == 1
    assert "src/example.py" in before.affected_paths
    with pytest.raises((ValueError, RuntimeError), match="different|collision|conflict"):
        verifier.record_change(replace(change, affected_paths=("src/conflicting.py",)))
    assert tasks.get("change-task").checkpoint == before
    assert len(state.events(stream_id="change:change-task")) == 1
    with closing(connect_sqlite(state.db_path)) as con:
        assert con.execute("SELECT COUNT(*) FROM agent_change_intents").fetchone()[0] == 1
