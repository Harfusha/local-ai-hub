from local_ai_hub.agent_events import SwarmPubSub


def test_wait_for_event_null_filter_requires_present_key(monkeypatch):
    bus = SwarmPubSub()
    subscribe = bus.subscribe

    def subscribe_with_events(topic, maxsize=100):
        sub_id, events = subscribe(topic, maxsize)
        events.put({"payload": {}})
        events.put({"payload": {"token": None}})
        return sub_id, events

    monkeypatch.setattr(bus, "subscribe", subscribe_with_events)
    result = bus.wait_for_event("filter-presence", timeout=1, filter_payload={"token": None})

    assert result["success"] is True
    assert result["message"] == {"token": None}
    assert bus.subscriber_count("filter-presence") == 0
