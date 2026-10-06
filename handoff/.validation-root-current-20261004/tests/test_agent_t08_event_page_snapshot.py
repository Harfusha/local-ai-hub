from local_ai_hub.agent_events import AgentEvent, AgentStateStore


def test_event_page_through_seq_excludes_events_appended_between_pages(tmp_path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    stream_id = "task:stable-snapshot"
    store.append(AgentEvent.create(stream_id, "task.updated", {"n": 1}))
    store.append(AgentEvent.create(stream_id, "task.updated", {"n": 2}))

    first = store.event_page(stream_id, after_seq=0, limit=1)
    snapshot_seq = first["last_seq"]
    assert [event["seq"] for event in first["events"]] == [1]
    assert snapshot_seq == 2
    assert first["has_more"] is True

    store.append(AgentEvent.create(stream_id, "task.updated", {"n": 3}))

    second = store.event_page(
        stream_id,
        after_seq=first["next_seq"],
        limit=1,
        through_seq=snapshot_seq,
    )
    assert [event["seq"] for event in second["events"]] == [2]
    assert second["last_seq"] == snapshot_seq
    assert second["has_more"] is False

    live = store.event_page(stream_id, after_seq=second["next_seq"], limit=1)
    assert [event["seq"] for event in live["events"]] == [3]
