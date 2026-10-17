from __future__ import annotations

import sqlite3
from pathlib import Path
import pytest

from local_ai_hub.agent_events import AgentEvent, AgentStateStore, AppendResult

def test_generated_event_identifiers_use_full_uuid_entropy_and_keep_supplied_keys():
    created = AgentEvent.create("stream-1", "test.event")
    restored = AgentEvent.from_dict(created.to_dict())

    for value, prefix in (
        (created.event_id, "evt_"),
        (created.idempotency_key, "idemp_"),
        (restored.event_id, "evt_"),
        (restored.idempotency_key, "idemp_"),
    ):
        assert value.startswith(prefix)
        suffix = value[len(prefix):]
        assert len(suffix) == 32
        assert int(suffix, 16) >= 0

    caller_key = AgentEvent.create("stream-1", "test.event", idempotency_key="client-key")
    assert caller_key.idempotency_key == "client-key"

    restored_key = AgentEvent.from_dict(
        {**created.to_dict(), "idempotency_key": "stored-key"}
    )
    assert restored_key.idempotency_key == "stored-key"


def test_from_dict_rejects_missing_canonical_event_fields():
    with pytest.raises(KeyError, match="event_id"):
        AgentEvent.from_dict({"stream_id": "stream-1", "kind": "test.event"})

    canonical = AgentEvent.create("stream-1", "test.event").to_dict()
    for field in ("correlation_id", "seq"):
        incomplete = {key: value for key, value in canonical.items() if key != field}
        with pytest.raises(KeyError, match=field):
            AgentEvent.from_dict(incomplete)


def test_from_dict_rejects_noncanonical_fields():
    canonical = AgentEvent.create("stream-1", "test.event").to_dict()
    with pytest.raises(ValueError, match="unexpected AgentEvent fields"):
        AgentEvent.from_dict({**canonical, "task_name": "legacy-alias"})


def test_schema_drift_fails_closed_without_deleting_durable_database(tmp_path: Path):
    db_path = tmp_path / "agent_state.sqlite3"
    con = sqlite3.connect(db_path)
    try:
        con.execute("""
            CREATE TABLE agent_events (
                stream_id TEXT NOT NULL, seq INTEGER NOT NULL, event_id TEXT NOT NULL,
                kind TEXT NOT NULL, payload TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                correlation_id TEXT NOT NULL, actor TEXT NOT NULL, created_at REAL NOT NULL,
                future_field TEXT, PRIMARY KEY (stream_id, seq), UNIQUE (stream_id, idempotency_key)
            )
        """)
        con.execute(
            "INSERT INTO agent_events VALUES ('task-1',1,'event-1','task.created','{}','key-1','','test',1.0,NULL)"
        )
        con.execute("CREATE TABLE durable_sentinel (value TEXT NOT NULL)")
        con.execute("INSERT INTO durable_sentinel (value) VALUES ('preserve')")
        con.commit()
    finally:
        con.close()
    original_bytes = db_path.read_bytes()

    with pytest.raises(RuntimeError, match="schema mismatch"):
        AgentStateStore(db_path)._ensure_schema()

    assert db_path.read_bytes() == original_bytes
    con = sqlite3.connect(db_path)
    try:
        assert con.execute("SELECT value FROM durable_sentinel").fetchone() == ("preserve",)
        assert con.execute("SELECT event_id FROM agent_events").fetchone() == ("event-1",)
    finally:
        con.close()


def test_append_returns_existing_sequence_for_same_idempotency_key(tmp_path: Path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    event = AgentEvent.create("task-1", "task.created", {"title": "index"}, "key-1")
    first = store.append(event)
    assert first.seq == 1
    assert first.duplicate is False
    second = store.append(event)
    assert second.seq == 1
    assert second.duplicate is True
    assert store.events("task-1") == [event.with_seq(1)]


def test_events_are_ordered_per_stream(tmp_path: Path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store.append(AgentEvent.create("task-1", "task.created", {}, "one"))
    store.append(AgentEvent.create("task-1", "task.planned", {}, "two"))
    assert [event.seq for event in store.events("task-1")] == [1, 2]


def test_events_stream_isolation_and_after_seq(tmp_path: Path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store.append(AgentEvent.create("task-1", "task.created", {"step": 1}, "k1"))
    store.append(AgentEvent.create("task-2", "task.created", {"step": 1}, "k2"))
    store.append(AgentEvent.create("task-1", "task.updated", {"step": 2}, "k3"))

    evs1 = store.events("task-1")
    assert len(evs1) == 2
    assert [e.seq for e in evs1] == [1, 2]

    evs2 = store.events("task-2")
    assert len(evs2) == 1
    assert evs2[0].seq == 1

    after = store.events("task-1", after_seq=1)
    assert len(after) == 1
    assert after[0].seq == 2


def test_snapshot_and_restore(tmp_path: Path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store.append(AgentEvent.create("task-1", "task.created", {"val": 10}, "k1"))
    snap_id = store.snapshot("task-1", {"status": "active", "val": 10}, seq=1)
    assert snap_id > 0
    latest = store.latest_snapshot("task-1")
    assert latest is not None
    assert latest["state"]["val"] == 10
    assert latest["seq"] == 1


def test_payload_size_limit(tmp_path: Path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3", max_payload_bytes=100)
    large_payload = {"data": "x" * 200}
    event = AgentEvent.create("task-1", "task.large", large_payload, "k-large")
    with pytest.raises(ValueError, match="payload exceeds"):
        store.append(event)


def test_subscribe_and_publish_events(tmp_path: Path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    q = store.subscribe()
    ev1 = AgentEvent.create("task-1", "task.created", {"step": 1}, "k1")
    store.append(ev1)
    received = q.get_nowait()
    assert received.kind == "task.created"
    assert received.seq == 1
    assert received.stream_id == "task-1"

    # Unsubscribe
    store.unsubscribe(q)
    ev2 = AgentEvent.create("task-1", "task.step", {"step": 2}, "k2")
    store.append(ev2)
    assert q.empty()
