from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub.agent_events import AgentEvent, AgentStateStore, AppendResult


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
