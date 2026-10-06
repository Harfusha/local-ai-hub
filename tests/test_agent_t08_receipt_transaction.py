from contextlib import closing
import sys

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_verification import VerificationStore
from local_ai_hub.agent_tasks import GoalContract, ScopeContext, TaskStore
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.commands import CommandBroker
from local_ai_hub.sqlite_support import connect_sqlite


def _command_broker_for_task(tmp_path, task_id):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    state_store = AgentStateStore(state_dir / "agent_state.sqlite3")
    tasks = TaskStore(state_store)
    verifier = VerificationStore(state_store, task_store=tasks)
    tasks.set_verification_store(verifier)
    tasks.create(
        GoalContract(goal="command receipt contract", acceptance_criteria=("tests",)),
        ScopeContext(task_id=task_id),
        task_id=task_id,
    )
    artifacts = ArtifactStore(state_dir)
    broker = CommandBroker(
        {
            "server": {"state_dir": str(state_dir)},
            "commands": {"enabled": True, "allow_read": True, "allow_validation": True},
        },
        artifacts,
        repo_state=type("RepoState", (), {"fingerprint": lambda _self, _cwd: {"fingerprint": "rev-1"}})(),
    )
    broker.set_verification_store(verifier)
    return broker, verifier, artifacts


def test_receipt_projection_helper_is_caller_transaction_atomic(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    tasks = TaskStore(state_store)
    task_id = "task-caller-owned-receipt"
    tasks.create(
        GoalContract(goal="caller-owned receipt", acceptance_criteria=("tests",)),
        ScopeContext(task_id=task_id),
        task_id=task_id,
    )
    stream_id = f"task:{task_id}"

    with closing(connect_sqlite(db_path, isolation_level=None)) as con:
        con.execute("BEGIN IMMEDIATE")
        pending, pending_event = tasks.add_verification_receipt_in_transaction(
            con, task_id, "tests", "receipt-rolled-back"
        )
        assert con.in_transaction is True
        assert pending is not None
        assert pending.verification_receipts == {"tests": "receipt-rolled-back"}
        assert pending_event is not None
        assert pending_event.kind == "task.verified"
        con.execute("ROLLBACK")

    rolled_back = tasks.get(task_id)
    assert rolled_back is not None
    assert rolled_back.verification_receipts == {}
    assert not any(event.kind == "task.verified" for event in state_store.events(stream_id))

    with closing(connect_sqlite(db_path, isolation_level=None)) as con:
        con.execute("BEGIN IMMEDIATE")
        committed, committed_event = tasks.add_verification_receipt_in_transaction(
            con, task_id, "tests", "receipt-committed"
        )
        assert con.in_transaction is True
        assert committed_event is not None
        con.execute("COMMIT")

    saved = tasks.get(task_id)
    assert saved is not None
    assert saved.verification_receipts == {"tests": "receipt-committed"}
    verified = [event for event in state_store.events(stream_id) if event.kind == "task.verified"]
    assert [event.event_id for event in verified] == [committed_event.event_id]


def test_command_receipt_is_durable_and_allows_task_completion(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    state_store = AgentStateStore(state_dir / "agent_state.sqlite3")
    tasks = TaskStore(state_store)
    verifier = VerificationStore(state_store, task_store=tasks)
    tasks.set_verification_store(verifier)
    task_id = "command-receipt-completion"
    tasks.create(
        GoalContract(goal="command receipt completion", acceptance_criteria=("tests",)),
        ScopeContext(task_id=task_id),
        task_id=task_id,
    )
    artifacts = ArtifactStore(state_dir)
    broker = CommandBroker(
        {
            "server": {"state_dir": str(state_dir)},
            "commands": {"enabled": True, "allow_read": True, "allow_validation": True},
        },
        artifacts,
        repo_state=type("RepoState", (), {"fingerprint": lambda _self, _cwd: {"fingerprint": "rev-1"}})(),
    )
    broker.set_verification_store(verifier)

    publication_calls = 0
    ordered_publication = state_store.ordered_event_publication

    def tracked_publication(con):
        nonlocal publication_calls
        publication_calls += 1
        return ordered_publication(con)

    monkeypatch.setattr(state_store, "ordered_event_publication", tracked_publication)
    (tmp_path / "tests").mkdir()
    result = broker.run(
        "python -m compileall tests",
        str(tmp_path),
        "tenant-a",
        task_id=task_id,
        criterion="tests",
    )

    assert result["exit_code"] == 0
    assert "verification_receipt_warning" not in result
    assert publication_calls == 1
    receipt_data = result["verification_receipt"]
    assert receipt_data["evidence_id"] == result["verification_evidence_id"]
    assert artifacts.get(receipt_data["evidence_id"], tenant="tenant-a")["success"] is True

    reloaded_state_store = AgentStateStore(state_dir / "agent_state.sqlite3")
    reloaded_tasks = TaskStore(reloaded_state_store)
    reloaded_verifier = VerificationStore(reloaded_state_store, task_store=reloaded_tasks)
    reloaded_tasks.set_verification_store(reloaded_verifier)
    completion = reloaded_verifier.completion(task_id)
    assert completion.complete is True
    assert len(completion.receipts) == 1
    assert any(
        event.kind == "verification.receipt_recorded"
        for event in reloaded_state_store.events(f"verification:{task_id}")
    )
    completed = reloaded_tasks.complete(
        task_id,
        reason="verified command receipt",
        idempotency_key="command-receipt-completion",
    )
    assert completed.status.value == "completed"


def test_failed_command_does_not_create_passed_verification_receipt(tmp_path):
    task_id = "failed-command-no-receipt"
    broker, verifier, _artifacts = _command_broker_for_task(tmp_path, task_id)
    command = f'"{sys.executable}" -c "raise SystemExit(7)"'

    result = broker.run(
        command,
        str(tmp_path),
        "tenant-a",
        task_id=task_id,
        criterion="tests",
    )

    assert result["success"] is False
    assert result["exit_code"] == 7
    assert "verification_receipt" not in result
    assert "verification_receipt_warning" not in result
    completion = verifier.completion(task_id)
    assert completion.complete is False
    assert completion.receipts == ()


@pytest.mark.parametrize("failure_point", ("evidence", "receipt"))
def test_receipt_persistence_failure_warns_without_overwriting_command_result(
    tmp_path, monkeypatch, failure_point
):
    task_id = f"receipt-write-failure-{failure_point}"
    broker, verifier, artifacts = _command_broker_for_task(tmp_path, task_id)

    def fail_write(*_args, **_kwargs):
        raise RuntimeError(f"synthetic {failure_point} persistence failure")

    if failure_point == "evidence":
        monkeypatch.setattr(artifacts, "put_json", fail_write)
    else:
        monkeypatch.setattr(verifier, "record", fail_write)
    command = f'"{sys.executable}" -c pass'

    result = broker.run(
        command,
        str(tmp_path),
        "tenant-a",
        task_id=task_id,
        criterion="tests",
    )

    assert result["success"] is True
    assert result["exit_code"] == 0
    assert result["verification_receipt_warning"] == (
        "command succeeded but durable verification evidence was unavailable"
    )
    assert "verification_receipt" not in result
    assert verifier.completion(task_id).receipts == ()
