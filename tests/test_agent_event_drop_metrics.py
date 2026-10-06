from local_ai_hub.agent_events import AgentEvent, AgentStateStore


def test_publish_reports_exact_per_stream_ranges_for_queue_overflow(tmp_path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    subscriber = store.subscribe(maxsize=1)
    first = AgentEvent.create("task-1", "task.created", {"title": "first"}, "key-1").with_seq(1)
    second = AgentEvent.create("task-2", "task.created", {"title": "second"}, "key-2").with_seq(5)
    third = AgentEvent.create("task-2", "task.updated", {"title": "third"}, "key-3").with_seq(6)

    store._publish(first)
    store._publish(second)
    store._publish(third)

    assert store.dropped_event_count == 3
    gap = subscriber.get_nowait()
    assert gap.stream_id == "agent_state"
    assert gap.kind == "agent_state.gap"
    assert gap.seq is None
    assert gap.payload["streams_truncated"] is False
    assert gap.payload["streams"] == [
        {"stream_id": "task-1", "from_seq": 1, "to_seq": 1},
        {"stream_id": "task-2", "from_seq": 5, "to_seq": 6},
    ]
    assert subscriber.empty()


def test_queue_overflow_bounds_gap_ranges_and_marks_omitted_streams(tmp_path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    subscriber = store.subscribe(maxsize=1)

    for seq in range(1, 131):
        event = AgentEvent.create(f"task-{seq}", "task.updated", {}, f"key-{seq}").with_seq(seq)
        store._publish(event)

    gap = subscriber.get_nowait()
    assert gap.kind == "agent_state.gap"
    assert len(gap.payload["streams"]) == 128
    assert gap.payload["streams_truncated"] is True
    assert gap.payload["streams"][-1] == {"stream_id": "task-128", "from_seq": 128, "to_seq": 128}
    assert store.dropped_event_count == 130


def test_queue_overflow_preserves_truncation_when_replacing_gap_marker(tmp_path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    subscriber = store.subscribe(maxsize=1)

    for task_number in range(1, 130):
        event = AgentEvent.create(
            f"task-{task_number}", "task.updated", {}, f"key-{task_number}"
        ).with_seq(1)
        store._publish(event)

    retained_stream_event = AgentEvent.create("task-128", "task.updated", {}, "key-next").with_seq(2)
    store._publish(retained_stream_event)

    gap = subscriber.get_nowait()
    assert gap.kind == "agent_state.gap"
    assert len(gap.payload["streams"]) == 128
    assert gap.payload["streams_truncated"] is True
    assert gap.payload["streams"][-1] == {
        "stream_id": "task-128",
        "from_seq": 1,
        "to_seq": 2,
    }
