from __future__ import annotations


def test_conversation_store_keeps_committed_turns_tenant_local() -> None:
    from local_ai_hub.conversations import ConversationStore

    store = ConversationStore(idle_ttl_seconds=60, max_turns=2)
    conversation = store.start(
        "tenant-a",
        {"model": "fast", "system": "system", "source": "delegate:general"},
    )

    reserved, error = store.reserve(conversation.conversation_id, "tenant-a")

    assert error == ""
    assert reserved is conversation
    store.complete(conversation.conversation_id, "tenant-a", "TASK:\nfirst", "first answer")
    resumed, error = store.reserve(conversation.conversation_id, "tenant-a")

    assert error == ""
    assert resumed.messages == [
        {"role": "user", "content": "TASK:\nfirst"},
        {"role": "assistant", "content": "first answer"},
    ]
    foreign, error = store.reserve(conversation.conversation_id, "tenant-b")

    assert foreign is None
    assert error == "conversation not found"


def test_conversation_store_rejects_active_and_expired_turns() -> None:
    from local_ai_hub.conversations import ConversationStore

    now = [100.0]
    store = ConversationStore(idle_ttl_seconds=5, max_turns=2, clock=lambda: now[0])
    conversation = store.start("tenant-a", {"model": "fast"})

    reserved, error = store.reserve(conversation.conversation_id, "tenant-a")

    assert reserved is conversation
    assert error == ""
    again, error = store.reserve(conversation.conversation_id, "tenant-a")

    assert again is None
    assert error == "conversation is already running"
    store.abort(conversation.conversation_id, "tenant-a")
    now[0] += 6
    expired, error = store.reserve(conversation.conversation_id, "tenant-a")

    assert expired is None
    assert error == "conversation not found"


def test_service_continues_with_pinned_route_without_persistent_cache() -> None:
    from local_ai_hub.conversations import ConversationStore
    from local_ai_hub.router import ModelRouter
    from local_ai_hub.services import LocalAIServices

    services = object.__new__(LocalAIServices)
    services.config = {
        "models": {"fast_code": "fast", "heavy_code": "heavy", "general": "general"},
        "routing": {"prefer_resident_model": False},
        "token_saving": {"max_local_input_tokens": 4000},
    }
    services.router = ModelRouter(services.config)
    services.conversations = ConversationStore(idle_ttl_seconds=60, max_turns=2)
    calls: list[dict] = []

    def fake_generate(model, prompt, system, max_tokens, temperature, tenant, source, priority, **kwargs):
        calls.append({
            "model": model, "prompt": prompt, "system": system, "max_tokens": max_tokens,
            "temperature": temperature, "tenant": tenant, "source": source, "priority": priority,
            **kwargs,
        })
        return {"success": True, "model": model, "text": f"answer {len(calls)}"}

    services._generate = fake_generate
    started = services.delegate({"task": "first question", "context": "initial facts", "conversation": True}, "tenant-a")

    assert started["success"] is True
    assert started["conversation_id"]
    continued = services.continue_conversation({"conversation_id": started["conversation_id"], "task": "clarify this"}, "tenant-a")

    assert continued["success"] is True
    assert continued["conversation_id"] == started["conversation_id"]
    assert calls[1]["model"] == calls[0]["model"]
    assert calls[1]["system"] == calls[0]["system"]
    assert "first question" in calls[1]["prompt"]
    assert "answer 1" in calls[1]["prompt"]
    assert "clarify this" in calls[1]["prompt"]
    assert calls[0]["internal"] is True
    assert calls[0]["use_cache"] is False
    assert calls[1]["use_cache"] is False


def test_service_discards_uncommitted_turn_after_model_failure() -> None:
    from local_ai_hub.conversations import ConversationStore
    from local_ai_hub.router import ModelRouter
    from local_ai_hub.services import LocalAIServices

    services = object.__new__(LocalAIServices)
    services.config = {
        "models": {"fast_code": "fast", "heavy_code": "heavy", "general": "general"},
        "routing": {"prefer_resident_model": False},
        "token_saving": {"max_local_input_tokens": 4000},
    }
    services.router = ModelRouter(services.config)
    services.conversations = ConversationStore(idle_ttl_seconds=60, max_turns=2)
    responses = iter((
        {"success": True, "model": "general", "text": "first answer"},
        {"success": False, "model": "general", "error": "model unavailable"},
    ))
    services._generate = lambda *args, **kwargs: next(responses)
    started = services.delegate({"task": "first", "conversation": True}, "tenant-a")
    failed = services.continue_conversation({"conversation_id": started["conversation_id"], "task": "failed follow-up"}, "tenant-a")
    conversation, error = services.conversations.reserve(started["conversation_id"], "tenant-a")

    assert failed["success"] is False
    assert error == ""
    assert conversation.messages == [
        {"role": "user", "content": "TASK:\nfirst\n"},
        {"role": "assistant", "content": "first answer"},
    ]


def test_conversation_debug_trace_redacts_transcript(monkeypatch) -> None:
    from types import SimpleNamespace

    from local_ai_hub import http_server

    class TraceStore:
        def __init__(self) -> None:
            self.response = None

        def finish(self, trace_id, *, state, response, error):
            self.response = {"trace_id": trace_id, "state": state, "response": response, "error": error}
            return True

    store = TraceStore()
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(debug_traces=store))
    handler = object.__new__(http_server.Handler)
    handler._debug_trace_id = "trace-1"
    handler._debug_trace_finished = False
    handler._debug_observer_token = None

    handler._redact_debug_trace()
    handler._finish_debug_trace(200, {"success": True, "text": "full transcript", "conversation_id": "opaque"})

    assert store.response == {
        "trace_id": "trace-1",
        "state": "done",
        "response": {"success": True, "conversation_redacted": True},
        "error": "",
    }
