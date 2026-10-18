from __future__ import annotations

from local_ai_hub.conversations import Conversation, ConversationStore
from local_ai_hub.delivery import (
    decide_delivery,
    is_async_delivery,
    is_bypass_delivery,
    is_valid_delivery_mode,
)


def test_conversation_dataclass_sanitizes_fields_and_helpers() -> None:
    conv = Conversation(
        conversation_id="  cid\x00-1  ",
        settings={"task_id": "task-1", "session_id": "session-1"},
        messages="not-a-list",  # type: ignore[arg-type]
        active=1,  # type: ignore[arg-type]
        updated_at=float("nan"),
    )
    assert conv.conversation_id == "cid-1"
    assert conv.settings == {"task_id": "task-1", "session_id": "session-1"}
    assert conv.messages == []
    assert conv.active is True
    assert conv.updated_at == 0.0
    assert conv.turn_count() == 0
    assert conv.is_empty() is True

    conv.messages.extend([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ])
    assert conv.turn_count() == 1
    assert conv.is_empty() is False
    as_dict = conv.to_dict()
    assert as_dict["conversation_id"] == "cid-1"
    assert as_dict["settings"] == {"task_id": "task-1", "session_id": "session-1"}
    assert as_dict["turn_count"] == 1


def test_conversation_rejects_retired_scope_metadata_by_presence() -> None:
    import pytest

    with pytest.raises(ValueError, match="retired conversation settings field: tenant"):
        Conversation(conversation_id="cid-1", settings={"tenant": None})


def test_conversation_store_nan_inf_bool_and_null_byte_resilience() -> None:
    store = ConversationStore(
        idle_ttl_seconds=float("nan"),
        active_ttl_seconds=float("inf"),
        max_turns=float("nan"),  # type: ignore[arg-type]
        max_conversations=float("inf"),  # type: ignore[arg-type]
    )
    assert store.idle_ttl_seconds == 900.0
    assert store.active_ttl_seconds == 1800.0
    assert store.max_turns == 12
    assert store.max_conversations == 1000
    assert store.count() == 0
    assert store.active_count() == 0

    bool_store = ConversationStore(
        idle_ttl_seconds=False,  # type: ignore[arg-type]
        active_ttl_seconds=False,  # type: ignore[arg-type]
        max_turns=False,  # type: ignore[arg-type]
        max_conversations=False,  # type: ignore[arg-type]
    )
    assert bool_store.idle_ttl_seconds == 900.0
    assert bool_store.active_ttl_seconds == 1800.0
    assert bool_store.max_turns == 12
    assert bool_store.max_conversations == 1000

    conv = store.start({"session_id": "session-a", "task_id": "task-a"})
    assert conv is not None
    assert conv.settings == {"session_id": "session-a", "task_id": "task-a"}
    assert store.count() == 1
    assert store.active_count() == 0

    reserved, err = store.reserve(f"  {conv.conversation_id}\x00 ")
    assert err == ""
    assert reserved is conv
    assert store.active_count() == 1

    completed = store.complete(conv.conversation_id, "u\x001", "a\x001")
    assert completed is True
    assert store.active_count() == 0
    assert conv.turn_count() == 1
    assert conv.messages[0]["content"] == "u1"
    assert conv.messages[1]["content"] == "a1"

    store.clear()
    assert store.count() == 0
    assert store.active_count() == 0


def test_decide_delivery_nan_inf_bool_and_helpers() -> None:
    assert is_valid_delivery_mode("sync") is True
    assert is_valid_delivery_mode("  AUTO\x00 ") is True
    assert is_valid_delivery_mode("invalid") is False
    assert is_valid_delivery_mode(True) is False

    res_nan = decide_delivery(
        "auto\x00",
        latency_budget_ms=float("nan"),
        observed_p95_ms=float("inf"),
        samples=float("nan"),  # type: ignore[arg-type]
        queue_age_ms=float("inf"),
        max_queue_age_ms=float("nan"),
    )
    assert res_nan["mode"] == "sync"
    assert res_nan["observed_p95_ms"] == 0.0
    assert res_nan["samples"] == 0
    assert "queue_age_ms" not in res_nan
    assert is_async_delivery(res_nan) is False
    assert is_bypass_delivery(res_nan) is False

    res_bool = decide_delivery(
        "auto",
        latency_budget_ms=True,  # type: ignore[arg-type]
        observed_p95_ms=True,  # type: ignore[arg-type]
        samples=True,  # type: ignore[arg-type]
        queue_age_ms=True,  # type: ignore[arg-type]
        max_queue_age_ms=True,  # type: ignore[arg-type]
    )
    assert res_bool["mode"] == "sync"
    assert res_bool["reason"] == "latency_budget_not_provided"
    assert res_bool["samples"] == 0

    res_async = decide_delivery(
        "auto",
        latency_budget_ms=100.0,
        observed_p95_ms=250.0,
        samples=12,
    )
    assert is_async_delivery(res_async) is True
    assert is_bypass_delivery(res_async) is False

    res_bypass = decide_delivery(
        "auto",
        queue_age_ms=500.0,
        max_queue_age_ms=100.0,
    )
    assert is_bypass_delivery(res_bypass) is True
    assert is_async_delivery(res_bypass) is False
