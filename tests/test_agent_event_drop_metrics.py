from local_ai_hub.agent_events import AgentEvent, AgentStateStore


def test_publish_counts_each_oldest_event_eviction(tmp_path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    subscriber = store.subscribe(maxsize=1)
    first = AgentEvent.create("task-1", "task.created", {"title": "first"}, "key-1")
    second = AgentEvent.create("task-1", "task.updated", {"title": "second"}, "key-2")
    third = AgentEvent.create("task-1", "task.updated", {"title": "third"}, "key-3")

    store._publish(first)
    store._publish(second)
    assert store.dropped_event_count == 1

    store._publish(third)
    assert store.dropped_event_count == 2
    assert subscriber.get_nowait() == third
    assert subscriber.empty()
