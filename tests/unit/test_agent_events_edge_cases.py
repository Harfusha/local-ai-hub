from __future__ import annotations

import pytest

from local_ai_hub.agent_events import (
    AgentEvent,
    AppendResult,
    SwarmPubSub,
)


def test_agent_event_sanitization_and_helpers() -> None:
    ev = AgentEvent(
        event_id=" evt-1\x00 ",
        stream_id=" stream-1\x00 ",
        kind=" task.created\x00 ",
        payload="not-a-dict",  # type: ignore[arg-type]
        idempotency_key=" \x00 ",
        correlation_id=" corr-1\x00 ",
        actor=" \x00 ",
        created_at=float("nan"),
        seq=-5,
    )
    assert ev.event_id == "evt-1"
    assert ev.stream_id == "stream-1"
    assert ev.kind == "task.created"
    assert ev.payload == {}
    assert ev.idempotency_key.startswith("idemp_")
    assert len(ev.idempotency_key) == len("idemp_") + 32
    assert ev.correlation_id == "corr-1"
    assert ev.actor == "agent"
    assert ev.created_at == 0.0
    assert ev.seq is None
    assert ev.is_persisted() is False
    assert ev.has_correlation() is True

    persisted_ev = ev.with_seq(4)
    assert persisted_ev.seq == 4
    assert persisted_ev.is_persisted() is True


def test_agent_event_from_dict_and_from_row_resilience() -> None:
    with pytest.raises(TypeError):
        AgentEvent.from_dict("invalid")  # type: ignore[arg-type]

    ev_dict = AgentEvent.from_dict({
        "stream_id": "s1\x00",
        "kind": "k1",
        "payload": "corrupt",
        "created_at": float("inf"),
        "seq": True,
    })
    assert ev_dict.stream_id == "s1"
    assert ev_dict.payload == {}
    assert ev_dict.created_at == 0.0
    assert ev_dict.seq is None

    row_corrupt = ("s1", 1, "e1", "k1", "{broken json", "id1", "", "actor1", 123.0)
    ev_row = AgentEvent.from_row(row_corrupt)
    assert ev_row.payload == {}
    assert ev_row.seq == 1
    assert ev_row.is_persisted() is True

    row_list_json = ("s1", 2, "e2", "k1", "[1, 2, 3]", "id2", "", "actor1", 124.0)
    ev_row2 = AgentEvent.from_row(row_list_json)
    assert ev_row2.payload == {}


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


def test_swarm_pubsub_sanitization_and_helpers() -> None:
    pubsub = SwarmPubSub(state_store=None, max_age_seconds=float("nan"))
    assert pubsub.max_age_seconds == 3600.0

    pubsub_neg = SwarmPubSub(state_store=None, max_age_seconds=-50.0)
    assert pubsub_neg.max_age_seconds == 3600.0

    sub_id, q = pubsub.subscribe("  Alerts\x00 ", maxsize=20)
    assert pubsub.subscriber_count("alerts") == 1
    assert pubsub.subscriber_count() == 1

    pub_res = pubsub.publish(" Alerts\x00 ", {"msg": "hello"})
    assert pub_res["success"] is True
    assert pub_res["topic"] == "alerts"
    assert pubsub.topic_count() == 1

    # Poll with NaN since_timestamp should still return messages
    poll_res = pubsub.poll("alerts", since_timestamp=float("nan"))
    assert poll_res["success"] is True
    assert poll_res["count"] == 1

    removed = pubsub.clear_topic("alerts")
    assert removed == 1
    assert pubsub.poll("alerts")["count"] == 0

    assert pubsub.unsubscribe("alerts", sub_id) is True
    assert pubsub.subscriber_count("alerts") == 0
