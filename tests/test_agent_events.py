from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub.agent_events import AgentEvent, AgentStateStore, AppendResult, SwarmPubSub


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


def test_swarm_pubsub_replays_after_coordinator_restart_from_exclusive_cursor(tmp_path: Path):
    db_path = tmp_path / "agent_state.sqlite3"
    publisher = SwarmPubSub(AgentStateStore(db_path), max_retained_messages=10)
    assert publisher.publish("work", {"step": 1})["success"] is True
    assert publisher.publish("work", {"step": 2})["success"] is True

    restarted = SwarmPubSub(AgentStateStore(db_path), max_retained_messages=10)
    result = restarted.poll("work", after_seq=1, limit=1)

    assert result["success"] is True
    assert [message["seq"] for message in result["messages"]] == [2]
    assert result["after_seq"] == 1
    assert result["next_seq"] == 2
    assert result["last_seq"] == 2
    assert result["has_more"] is False
    assert result["has_gap"] is False


def test_swarm_pubsub_reports_expired_cursor_gap_after_bounded_retention(tmp_path: Path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    pubsub = SwarmPubSub(store, max_retained_messages=2)
    for step in range(1, 4):
        assert pubsub.publish("work", {"step": step})["success"] is True

    page = store.event_page("pubsub:work", after_seq=0, limit=10)
    result = pubsub.poll("work", after_seq=0, limit=10)

    assert [event.seq for event in page["events"]] == [2, 3]
    assert page["first_retained_seq"] == 2
    assert page["has_gap"] is True
    assert [message["seq"] for message in result["messages"]] == [2, 3]
    assert result["first_retained_seq"] == 2
    assert result["has_gap"] is True
    assert result["gap"] == {
        "reason": "retention",
        "requested_after_seq": 0,
        "first_retained_seq": 2,
        "last_seq": 3,
    }
    assert result["next_seq"] == 3


def test_swarm_pubsub_poll_page_limit_returns_continuation_cursor(tmp_path: Path):
    pubsub = SwarmPubSub(AgentStateStore(tmp_path / "agent_state.sqlite3"), max_retained_messages=10)
    for step in range(1, 4):
        assert pubsub.publish("work", {"step": step})["success"] is True

    first_page = pubsub.poll("work", after_seq=0, limit=2)
    second_page = pubsub.poll("work", after_seq=first_page["next_seq"], limit=2)

    assert [message["seq"] for message in first_page["messages"]] == [1, 2]
    assert first_page["has_more"] is True
    assert first_page["next_seq"] == 2
    assert [message["seq"] for message in second_page["messages"]] == [3]
    assert second_page["has_more"] is False


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
