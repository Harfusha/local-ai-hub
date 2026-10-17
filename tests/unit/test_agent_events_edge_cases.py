from __future__ import annotations

import pytest

from local_ai_hub.agent_events import (
    AgentEvent,
    AppendResult,
    SwarmPubSub,
)


def test_agent_event_valid_identity_and_helpers() -> None:
    ev = AgentEvent.create("stream-1", "task.created", correlation_id="corr-1")
    assert ev.is_persisted() is False
    assert ev.has_correlation() is True
    persisted_ev = ev.with_seq(4)
    assert persisted_ev.seq == 4
    assert persisted_ev.is_persisted() is True


def test_agent_event_from_dict_and_from_row_reject_corruption() -> None:
    with pytest.raises(TypeError):
        AgentEvent.from_dict("invalid")
    with pytest.raises(KeyError):
        AgentEvent.from_dict({"stream_id": "s1", "payload": "corrupt"})
    row_corrupt = ("s1", 1, "e1", "k1", "{broken json", "id1", "", "actor1", 123.0)
    with pytest.raises(ValueError):
        AgentEvent.from_row(row_corrupt)
    row_list_json = ("s1", 2, "e2", "k1", "[1, 2, 3]", "id2", "", "actor1", 124.0)
    with pytest.raises(TypeError):
        AgentEvent.from_row(row_list_json)
    ev = AgentEvent.create("s1", "k1").with_seq(1)
    assert AgentEvent.from_dict(ev.to_dict()) == ev


def test_append_result_helpers_and_serialization() -> None:
    ev = AgentEvent.create("s1", "k1").with_seq(1)
    ok = AppendResult(seq=1, duplicate=False, event=ev)
    assert ok.succeeded() is True
    assert ok.is_error() is False
    d = ok.to_dict()
    assert d["seq"] == 1
    assert d["duplicate"] is False
    assert d["event"]["seq"] == 1

    err = AppendResult(seq=0, duplicate=False, retryable=True, error="busy")
    assert err.succeeded() is False
    assert err.is_error() is True

    missing_event = AppendResult(seq=1, duplicate=False)
    assert missing_event.succeeded() is False
    assert missing_event.is_error() is True

    missing_sequence = AppendResult(seq=0, duplicate=False)
    assert missing_sequence.succeeded() is False
    assert missing_sequence.is_error() is True


def test_swarm_pubsub_strict_inputs_and_helpers() -> None:
    for age in (float("nan"), -50.0, True):
        with pytest.raises(ValueError):
            SwarmPubSub(state_store=None, max_age_seconds=age)
    pubsub = SwarmPubSub(state_store=None)
    with pytest.raises(ValueError):
        pubsub.subscribe("Alerts\x00", maxsize=20)
    assert pubsub.publish("Alerts\x00", {"msg": "hello"})["success"] is False
    sub_id, queue = pubsub.subscribe("Alerts", maxsize=20)
    assert pubsub.subscriber_count("alerts") == 1
    assert pubsub.subscriber_count() == 1
    assert pubsub.publish("Alerts", {"msg": "hello"})["success"] is True
    assert pubsub.topic_count() == 1
    with pytest.raises(ValueError):
        pubsub.poll("alerts", since_timestamp=float("nan"))
    assert pubsub.poll("alerts")["count"] == 1
    assert pubsub.clear_topic("alerts") == 1
    assert pubsub.poll("alerts")["count"] == 0
    assert pubsub.unsubscribe("alerts", sub_id) is True
    assert pubsub.subscriber_count("alerts") == 0
