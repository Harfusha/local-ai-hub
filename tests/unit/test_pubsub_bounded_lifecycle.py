"""Deferred bundle cases; durable state only in tmp_path, no live Hub access."""
import pytest

from local_ai_hub import agent_events
from local_ai_hub.agent_events import AgentStateStore, SwarmPubSub
from local_ai_hub.pubsub_limits import snapshot_message


def test_ephemeral_capacity_refuses_new_topic_without_losing_existing_history():
    bus = SwarmPubSub(max_topics=1)
    assert bus.publish("existing", {"n": 1})["success"]
    rejected = bus.publish("new", {"n": 2})
    assert not rejected["success"] and not rejected["replay_available"]
    assert bus.poll("existing")["messages"][0]["payload"] == {"n": 1}
    assert list(bus._topics) == ["existing"]


def test_cache_byte_capacity_preserves_admitted_history():
    bus = SwarmPubSub(max_cached_bytes=1024)
    assert bus.publish("existing", "x" * 700)["success"]
    assert not bus.publish("new", "y" * 700)["success"]
    assert bus._cached_bytes <= 1024
    assert bus.poll("existing")["messages"][0]["payload"] == {"text": "x" * 700}


def test_compaction_releases_expired_cache_without_disconnect(monkeypatch):
    tick = [10.0]
    monkeypatch.setattr(agent_events.time, "time", lambda: tick[0])
    bus = SwarmPubSub(max_topics=1, max_age_seconds=5)
    sub_id, queue = bus.subscribe("old", maxsize=10)
    assert bus.publish("old", "payload")["success"]
    tick[0] = 20
    result = bus.compact()
    assert result["topics_pruned"] == 1 and result["messages_evicted"] == 1
    assert result["cached_bytes"] == 0 and result["subscribers_evicted"] == 0
    assert sub_id in bus._subscribers["old"] and queue.qsize() == 1
    assert bus.poll("old", since_timestamp=9)["has_gap"]
    assert bus.publish("new", "fresh")["success"]


def test_subscription_count_and_total_slots_are_reclaimed_only_on_unsubscribe():
    bus = SwarmPubSub(max_subscribers=2, max_queue_slots=20)
    first, _queue = bus.subscribe("a", maxsize=10)
    bus.subscribe("b", maxsize=10)
    with pytest.raises(ValueError, match="capacity"):
        bus.subscribe("c", maxsize=10)
    bus.compact()
    assert bus._subscriber_count == 2 and bus._queue_slots == 20
    assert bus.unsubscribe("a", first)
    assert not bus.unsubscribe("a", first)
    assert "a" not in bus._subscribers
    bus.subscribe("c", maxsize=10)
    assert bus._subscriber_count == 2 and bus._queue_slots == 20


def test_default_admission_supports_thirty_live_subscribers():
    bus = SwarmPubSub()
    subscriptions = [bus.subscribe("topic") for _index in range(30)]
    assert bus._subscriber_count == 30 and bus._queue_slots == 3000
    assert bus.publish("topic", "message")["success"]
    assert all(queue.get_nowait()["payload"] == {"text": "message"} for _sub_id, queue in subscriptions)


@pytest.mark.parametrize("subscribers,slots,accepted", [(1, 1000, 1), (10, 20, 2)])
def test_subscription_count_and_slot_limits_apply_independently(subscribers, slots, accepted):
    bus = SwarmPubSub(max_subscribers=subscribers, max_queue_slots=slots)
    for index in range(accepted):
        bus.subscribe(f"topic-{index}", maxsize=10)
    with pytest.raises(ValueError, match="capacity"):
        bus.subscribe("overflow", maxsize=10)
    assert bus._subscriber_count == accepted and bus._queue_slots == accepted * 10


def test_durable_publish_replay_and_idempotency_survive_unavailable_cache(tmp_path):
    path = tmp_path / "events.sqlite3"
    bus = SwarmPubSub(AgentStateStore(path), max_cached_bytes=1)
    _sub_id, queue = bus.subscribe("topic", maxsize=10)
    published = bus.publish("topic", {"n": 1}, idempotency_key="opaque ")
    assert published["success"] and published["durable"] and not published["cache_retained"]
    assert queue.get_nowait()["payload"] == {"n": 1}
    assert bus._cached_bytes == 0 and bus._topics == {}
    duplicate = bus.publish("topic", {"n": 1}, idempotency_key="opaque ")
    assert duplicate["duplicate"] and duplicate["cursor"] == published["cursor"]
    assert queue.empty()
    collision = bus.publish("topic", {"n": 2}, idempotency_key="opaque ")
    assert not collision["success"]
    distinct = bus.publish("topic", {"n": 2}, idempotency_key="opaque")
    assert distinct["success"] and distinct["cursor"] > published["cursor"]
    restarted = SwarmPubSub(AgentStateStore(path))
    replay = restarted.poll("topic")
    assert replay["durable"] and replay["replay_available"]
    assert [message["payload"] for message in replay["messages"]] == [{"n": 1}, {"n": 2}]


def test_payload_ownership_separates_input_cache_and_subscribers():
    bus = SwarmPubSub()
    _first, first_queue = bus.subscribe("topic", maxsize=10)
    _second, second_queue = bus.subscribe("topic", maxsize=10)
    original = {"values": [1]}
    assert bus.publish("topic", original)["success"]
    original["values"].append(2)
    first_queue.get_nowait()["payload"]["values"].append(3)
    assert second_queue.get_nowait()["payload"] == {"values": [1]}
    page = bus.poll("topic")
    page["messages"][0]["payload"]["values"].append(4)
    assert bus.poll("topic")["messages"][0]["payload"] == {"values": [1]}


def test_ephemeral_ring_reports_more_and_retention_gap(monkeypatch):
    tick = [1.0]
    monkeypatch.setattr(agent_events.time, "time", lambda: tick[0])
    bus = SwarmPubSub()
    for number in range(205):
        tick[0] = number + 1.0
        assert bus.publish("topic", {"n": number})["success"]
    page = bus.poll("topic", since_timestamp=2, limit=10)
    assert page["has_gap"] and page["has_more"]
    assert page["messages"][0]["payload"] == {"n": 5}
    assert len(bus._topics["topic"]) == 200
    assert bus._cached_bytes == sum(bus._topic_sizes["topic"])


def test_live_overflow_accounts_for_dropped_queue_tasks():
    bus = SwarmPubSub()
    _sub_id, queue = bus.subscribe("topic", maxsize=10)
    for number in range(11):
        assert bus.publish("topic", {"n": number})["success"]
    marker = None
    while not queue.empty():
        item = queue.get_nowait()
        if item["kind"] == "pubsub.gap":
            marker = item
        queue.task_done()
    assert marker is not None and marker["payload"]["lost_count"] == 2
    assert queue.unfinished_tasks == 0


@pytest.mark.parametrize("payload", [{"value": float("nan")}, {"value": "x" * 1000}, {1: "bad key"}])
def test_invalid_payload_is_rejected_before_durable_append(payload):
    class Store:
        enabled = True

        def append(self, *args, **kwargs):
            pytest.fail("invalid payload reached durable append")

    bus = SwarmPubSub(Store(), max_message_bytes=128)
    result = bus.publish("topic", payload)
    assert not result["success"] and result["terminal"] and not result["retryable"]
    assert not bus._topics


def test_snapshot_rejects_cycles_depth_and_escaped_byte_overflow():
    cyclic = {}
    cyclic["self"] = cyclic
    with pytest.raises(ValueError, match="cyclic"):
        snapshot_message(cyclic, 4096)
    deep = {}
    for _index in range(34):
        deep = {"next": deep}
    with pytest.raises(ValueError, match="structure"):
        snapshot_message(deep, 4096)
    with pytest.raises(ValueError, match="byte limit"):
        snapshot_message({"text": "\x00" * 30}, 128)
    with pytest.raises(ValueError, match="structure"):
        snapshot_message(list(range(5000)), 65_536)


def test_shared_input_container_is_copied_without_false_cycle_detection():
    shared = [1, 2]
    result, size = snapshot_message({"a": shared, "b": shared}, 1024)
    assert result == {"a": [1, 2], "b": [1, 2]} and size > 0
    assert result["a"] is not result["b"]
