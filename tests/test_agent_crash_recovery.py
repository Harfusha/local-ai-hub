from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskStatus, TaskStore
from local_ai_hub.agent_verification import ChangeIntent, OutcomeRecord, VerificationStore
from local_ai_hub.swarm import SwarmCoordinator, SwarmState


def test_incompatible_durable_event_schema_is_preserved_with_recovery_backup(tmp_path):
    db_path = tmp_path / "agent-state.sqlite3"
    with closing(sqlite3.connect(db_path)) as con:
        con.execute(
            "CREATE TABLE agent_events (stream_id TEXT, seq INTEGER, legacy_payload TEXT)"
        )
        con.execute(
            "INSERT INTO agent_events VALUES (?, ?, ?)",
            ("durable", 1, "preserve-me"),
        )
        con.commit()

    store = AgentStateStore(db_path)
    with pytest.raises(RuntimeError, match="schema mismatch") as caught:
        store._ensure_schema()

    backup_path = getattr(caught.value, "backup_path", None)
    assert backup_path is not None
    assert backup_path.is_file()
    for path in (db_path, backup_path):
        with closing(sqlite3.connect(path)) as con:
            row = con.execute(
                "SELECT stream_id, seq, legacy_payload FROM agent_events"
            ).fetchone()
        assert row == ("durable", 1, "preserve-me")


def test_task_update_rolls_back_projection_when_event_insert_fails(tmp_path):
    state_store = AgentStateStore(tmp_path / "agent-state.sqlite3")
    tasks = TaskStore(state_store)
    task = tasks.create(
        GoalContract(goal="atomic update"),
        ScopeContext(task_id="atomic-update"),
        task_id="atomic-update",
    )
    tasks.transition(
        task.task_id,
        TaskStatus.ACTIVE,
        reason="start",
        actor="test",
        idempotency_key="start",
    )
    with closing(sqlite3.connect(state_store.db_path)) as con:
        con.execute(
            """
            CREATE TRIGGER fail_task_transition BEFORE INSERT ON agent_events
            WHEN NEW.kind = 'task.transitioned' AND NEW.idempotency_key = 'fail-update'
            BEGIN
                SELECT RAISE(ABORT, 'atomic update failure');
            END;
            """
        )
        con.commit()

    with pytest.raises(sqlite3.IntegrityError, match="atomic update failure"):
        tasks.transition(
            task.task_id,
            TaskStatus.WAITING,
            reason="wait",
            actor="test",
            idempotency_key="fail-update",
        )

    current = tasks.get(task.task_id)
    assert current is not None
    assert current.status == TaskStatus.ACTIVE
    assert all(
        event.idempotency_key != "fail-update"
        for event in state_store.events(stream_id=f"task:{task.task_id}")
    )


def test_separate_event_outbox_recovers_after_crash_after_commit(tmp_path, monkeypatch):
    swarm_db = tmp_path / "swarms.sqlite3"
    event_db = tmp_path / "events.sqlite3"
    state_store = AgentStateStore(event_db)
    coordinator = SwarmCoordinator(swarm_db, state_store=state_store)
    original_append = state_store.append

    def append_then_crash(event):
        original_append(event)
        raise SystemExit("simulated crash after durable event append")

    monkeypatch.setattr(state_store, "append", append_then_crash)
    with pytest.raises(SystemExit, match="simulated crash"):
        coordinator.dispatch(
            goal="Recover event after restart",
            target_paths=[],
            test_command="pytest -q",
        )

    with closing(sqlite3.connect(swarm_db)) as con:
        swarm_id = con.execute("SELECT swarm_id FROM agent_swarms").fetchone()[0]
        pending = con.execute(
            "SELECT COUNT(*) FROM agent_swarm_outbox WHERE status = 'pending'"
        ).fetchone()[0]
    assert pending == 1
    assert len(AgentStateStore(event_db).events(stream_id=f"swarm:{swarm_id}")) == 1

    restarted_state = AgentStateStore(event_db)
    restarted = SwarmCoordinator(swarm_db, state_store=restarted_state)

    assert restarted.get_status(swarm_id)["state"] == SwarmState.CODING.value
    assert len(restarted_state.events(stream_id=f"swarm:{swarm_id}")) == 1
    with closing(sqlite3.connect(swarm_db)) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM agent_swarm_outbox WHERE status = 'pending'"
        ).fetchone()[0] == 0


def test_event_idempotency_key_rejects_different_payload(tmp_path):
    store = AgentStateStore(tmp_path / "events.sqlite3")
    original = AgentEvent.create(
        stream_id="same-stream",
        kind="task.updated",
        payload={"status": "active"},
        idempotency_key="same-operation",
    )
    assert store.append(original).event is not None

    conflict = AgentEvent.create(
        stream_id="same-stream",
        kind="task.updated",
        payload={"status": "failed"},
        idempotency_key="same-operation",
    )
    result = store.append(conflict)

    assert result.duplicate is False
    assert result.error is not None
    assert "idempotency key conflict" in result.error


@pytest.mark.parametrize("record_kind", ["change", "outcome"])
def test_verifier_projection_rolls_back_when_event_projection_write_fails(tmp_path, record_kind):
    store = AgentStateStore(tmp_path / f"{record_kind}.sqlite3")
    verifier = VerificationStore(store)
    change = ChangeIntent.create("atomic-record", ["src/app.py"])
    if record_kind == "change":
        stream_id = f"change:{change.task_id}"
        with closing(sqlite3.connect(store.db_path)) as con, con:
            con.execute(
                "CREATE TRIGGER reject_change BEFORE INSERT ON agent_change_intents "
                "BEGIN SELECT RAISE(ABORT, 'projection rejected'); END"
            )
        with pytest.raises(sqlite3.IntegrityError, match="projection rejected"):
            verifier.record_change(change)
        with closing(sqlite3.connect(store.db_path)) as con:
            assert con.execute("SELECT COUNT(*) FROM agent_change_intents").fetchone()[0] == 0
    else:
        outcome = OutcomeRecord.accepted(change.change_id, task_id=change.task_id)
        stream_id = f"outcome:{change.change_id}"
        with closing(sqlite3.connect(store.db_path)) as con, con:
            con.execute(
                "CREATE TRIGGER reject_outcome BEFORE INSERT ON agent_outcomes "
                "BEGIN SELECT RAISE(ABORT, 'projection rejected'); END"
            )
        with pytest.raises(sqlite3.IntegrityError, match="projection rejected"):
            verifier.record_outcome(outcome)
        with closing(sqlite3.connect(store.db_path)) as con:
            assert con.execute("SELECT COUNT(*) FROM agent_outcomes").fetchone()[0] == 0
    assert store.events(stream_id=stream_id) == []
