from contextlib import closing

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_tasks import GoalContract, ScopeContext, TaskStore
from local_ai_hub.sqlite_support import connect_sqlite


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
