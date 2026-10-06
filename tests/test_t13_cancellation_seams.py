from __future__ import annotations

import threading
from types import SimpleNamespace

from local_ai_hub.http_server import (
    _ActiveTranscriptionRegistry,
    _invoke_cancellable_request,
)
from local_ai_hub.services import LocalAIServices


def test_conversation_request_is_cancelled_and_drains_before_release():
    registry = _ActiveTranscriptionRegistry()
    started = threading.Event()
    finished = threading.Event()
    results = []

    def service(_payload, _tenant, *, cancel_event):
        started.set()
        assert cancel_event.wait(1.0)
        return {"success": False, "cancelled": True, "reason": "cancelled"}

    def invoke():
        results.append(_invoke_cancellable_request(registry, service, {}, "tenant"))
        finished.set()

    request = threading.Thread(target=invoke)
    request.start()
    assert started.wait(1.0)

    registry.enter_gaming()
    release = registry.cancel_and_wait(1.0)

    request.join(timeout=1.0)
    assert not request.is_alive()
    assert finished.is_set()
    assert release == {
        "state": "cancelled", "inference_active": False, "active": 0, "cancelled": True,
    }
    assert results[0]["cancelled"] is True


def test_conversation_drain_timeout_fails_closed_and_blocks_new_request():
    registry = _ActiveTranscriptionRegistry()
    token, _event = registry.begin()
    registry.enter_gaming()

    release = registry.cancel_and_wait(0.0)
    new_token, new_event = registry.begin()

    assert release["state"] == "timed_out"
    assert release["inference_active"] is True
    assert new_event.is_set()

    registry.finish(token, {"success": False, "cancelled": True, "reason": "cancelled"})
    registry.finish(new_token, {"success": False, "cancelled": True, "reason": "cancelled"})
    registry.enter_active()
    resumed_token, resumed_event = registry.begin()
    assert not resumed_event.is_set()
    registry.finish(resumed_token, {"success": True})


def test_cancellable_invocation_falls_back_for_legacy_callback():
    registry = _ActiveTranscriptionRegistry()
    seen = []

    result = _invoke_cancellable_request(
        registry, lambda payload, tenant: seen.append((payload, tenant)) or {"success": True},
        {"task": "x"}, "tenant",
    )

    assert result["success"] is True
    assert seen == [({"task": "x"}, "tenant")]


def test_pause_gate_skips_legacy_uncancellable_callback():
    registry = _ActiveTranscriptionRegistry()
    registry.enter_gaming()
    calls = []

    result = _invoke_cancellable_request(
        registry, lambda *_args: calls.append("started") or {"success": True}, {}, "tenant",
    )

    assert result["cancelled"] is True
    assert calls == []
    assert registry.active_count() == 0


def test_cancelled_new_conversation_discards_reserved_turn():
    cancel_event = threading.Event()
    calls = []

    class Conversations:
        def start_reserved(self, _tenant, _settings):
            return SimpleNamespace(conversation_id="new-id")

        def discard(self, conversation_id, tenant):
            calls.append(("discard", conversation_id, tenant))

        def complete(self, *_args):
            calls.append(("complete",))
            return True

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {}
    services.conversations = Conversations()

    def generate(*_args, **_kwargs):
        cancel_event.set()
        return {"success": True, "text": "late answer"}

    services._generate = generate
    result = services._start_conversation(
        tenant="tenant", prompt="p", route={"model": "small"}, system="s",
        max_tokens=16, temperature=0.0, source="delegate:test", priority=1,
        cancel_event=cancel_event,
    )

    assert result["cancelled"] is True
    assert result["conversation_id"] == "new-id"
    assert calls == [("discard", "new-id", "tenant")]


def test_cancelled_continuation_aborts_reservation_without_commit():
    cancel_event = threading.Event()
    calls = []
    conversation = SimpleNamespace(
        messages=[],
        settings={
            "model": "small", "system": "sys", "max_tokens": 16,
            "temperature": 0.0, "source": "delegate:test", "priority": 1,
            "route": {"model": "small"},
        },
    )

    class Conversations:
        def reserve(self, _conversation_id, _tenant):
            return conversation, None

        def abort(self, conversation_id, tenant):
            calls.append(("abort", conversation_id, tenant))

        def complete(self, *_args):
            calls.append(("complete",))
            return True

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {}
    services.conversations = Conversations()

    def generate(*_args, **_kwargs):
        cancel_event.set()
        return {"success": True, "text": "late answer"}

    services._generate = generate
    result = services.continue_conversation(
        {"conversation_id": "existing-id", "task": "next"}, "tenant",
        cancel_event=cancel_event,
    )

    assert result["cancelled"] is True
    assert result["conversation_id"] == "existing-id"
    assert calls == [("abort", "existing-id", "tenant")]
