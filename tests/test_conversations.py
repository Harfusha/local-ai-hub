from __future__ import annotations


def test_conversation_store_keeps_committed_turns_by_conversation_id() -> None:
    from local_ai_hub.conversations import ConversationStore

    store = ConversationStore(idle_ttl_seconds=60, max_turns=2)
    conversation = store.start(
        {"model": "fast", "system": "system", "source": "delegate:general"},
    )

    reserved, error = store.reserve(conversation.conversation_id)

    assert error == ""
    assert reserved is conversation
    store.complete(conversation.conversation_id, "TASK:\nfirst", "first answer")
    resumed, error = store.reserve(conversation.conversation_id)

    assert error == ""
    assert resumed.messages == [
        {"role": "user", "content": "TASK:\nfirst"},
        {"role": "assistant", "content": "first answer"},
    ]
    missing, error = store.reserve("unknown-conversation")

    assert missing is None
    assert error == "conversation not found"


def test_conversation_store_rejects_active_and_expired_turns() -> None:
    from local_ai_hub.conversations import ConversationStore

    now = [100.0]
    store = ConversationStore(idle_ttl_seconds=5, max_turns=2, clock=lambda: now[0])
    conversation = store.start({"model": "fast"})

    reserved, error = store.reserve(conversation.conversation_id)

    assert reserved is conversation
    assert error == ""
    again, error = store.reserve(conversation.conversation_id)

    assert again is None
    assert error == "conversation is already running"
    store.abort(conversation.conversation_id)
    now[0] += 6
    expired, error = store.reserve(conversation.conversation_id)

    assert expired is None
    assert error == "conversation not found"


def test_expired_active_conversation_cannot_be_completed_or_revived_by_abort() -> None:
    from local_ai_hub.conversations import ConversationStore

    for finish in ("complete", "abort"):
        now = [100.0]
        store = ConversationStore(
            idle_ttl_seconds=5,
            active_ttl_seconds=8,
            max_turns=2,
            clock=lambda: now[0],
        )
        conversation = store.start({"model": "fast"})
        reserved, error = store.reserve(conversation.conversation_id)
        assert reserved is conversation
        assert error == ""

        now[0] += 9
        if finish == "complete":
            finished = store.complete(conversation.conversation_id, "late prompt", "late answer")
        else:
            finished = store.abort(conversation.conversation_id)

        assert finished is False
        assert conversation.conversation_id not in store._items


def test_service_reserves_new_conversation_before_competing_start_can_evict_it() -> None:
    from local_ai_hub.conversations import ConversationStore
    from local_ai_hub.services import LocalAIServices

    class InterleavingConversationStore(ConversationStore):
        competing_start = "not attempted"

        def start(self, settings):
            conversation = super().start(settings)
            if conversation is not None:
                self.competing_start = super().start(settings)
            return conversation

        def start_reserved(self, settings):
            conversation = super().start_reserved(settings)
            self.competing_start = super().start(settings)
            return conversation

    services = object.__new__(LocalAIServices)
    services.config = {"token_saving": {"max_local_input_tokens": 4000}}
    services.conversations = InterleavingConversationStore(idle_ttl_seconds=1000, max_conversations=1)
    services._generate = lambda *args, **kwargs: {"success": True, "text": "answer"}

    result = services._start_conversation(
        prompt="question", route={"model": "m"}, system="system",
        max_tokens=32, temperature=0.0, source="delegate:general", priority=0,
    )

    assert result["success"] is True
    assert result["conversation_id"] in services.conversations._items
    assert services.conversations.competing_start is None


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

    def fake_generate(model, prompt, system, max_tokens, temperature, *, source, priority, **kwargs):
        calls.append({
            "model": model, "prompt": prompt, "system": system, "max_tokens": max_tokens,
            "temperature": temperature, "source": source, "priority": priority,
            **kwargs,
        })
        return {"success": True, "model": model, "text": f"answer {len(calls)}"}

    services._generate = fake_generate
    started = services.delegate({"task": "first question", "context": "initial facts", "conversation": True})

    assert started["success"] is True
    assert started["conversation_id"]
    continued = services.continue_conversation({"conversation_id": started["conversation_id"], "task": "clarify this"})

    assert continued["success"] is True
    assert continued["conversation_id"] == started["conversation_id"]
    assert calls[1]["model"] == calls[0]["model"]
    assert calls[1]["system"] == calls[0]["system"]
    assert "measured_cloud_context_tokens" not in calls[0]
    assert "measured_cloud_context_tokens" not in calls[1]
    assert "first question" in calls[1]["prompt"]
    assert "answer 1" in calls[1]["prompt"]
    assert "clarify this" in calls[1]["prompt"]
    assert calls[0]["internal"] is True
    assert calls[0]["use_cache"] is False
    assert calls[1]["use_cache"] is False


def test_regular_delegate_does_not_claim_local_context_as_cloud_savings() -> None:
    from local_ai_hub.router import ModelRouter
    from local_ai_hub.services import LocalAIServices

    services = object.__new__(LocalAIServices)
    services.config = {
        "models": {"fast_code": "fast", "heavy_code": "heavy", "general": "general"},
        "routing": {"prefer_resident_model": False},
        "token_saving": {"max_local_input_tokens": 4000},
    }
    services.router = ModelRouter(services.config)
    calls: list[dict] = []

    def fake_generate(model, prompt, system, max_tokens, temperature, *, source, priority, **kwargs):
        calls.append(kwargs)
        return {"success": True, "model": model, "text": "answer"}

    services._generate = fake_generate
    result = services.delegate(
        {"task": "inspect the repository", "context": "locally packed repository facts"},
    )

    assert result["success"] is True
    assert len(calls) == 1
    assert calls[0]["semantic_query"] == "inspect the repository"
    assert calls[0]["semantic_context_fingerprint"]
    assert "measured_cloud_context_tokens" not in calls[0]


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
    started = services.delegate({"task": "first", "conversation": True})
    failed = services.continue_conversation({"conversation_id": started["conversation_id"], "task": "failed follow-up"})
    conversation, error = services.conversations.reserve(started["conversation_id"])

    assert failed["success"] is False
    assert error == ""
    assert conversation.messages == [
        {"role": "user", "content": "TASK:\nfirst\n"},
        {"role": "assistant", "content": "first answer"},
    ]


def test_conversation_debug_trace_preserves_opt_in_transcript(monkeypatch) -> None:
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

    handler._finish_debug_trace(200, {"success": True, "text": "full transcript", "conversation_id": "opaque"})

    assert store.response == {
        "trace_id": "trace-1",
        "state": "done",
        "response": {"success": True, "text": "full transcript", "conversation_id": "opaque"},
        "error": "",
    }


def test_conversation_store_purges_abandoned_active_turns() -> None:
    from local_ai_hub.conversations import ConversationStore

    now = [100.0]
    store = ConversationStore(idle_ttl_seconds=10, active_ttl_seconds=30, clock=lambda: now[0])
    conversation = store.start({"model": "fast"})

    reserved, error = store.reserve(conversation.conversation_id)
    assert error == ""
    assert reserved.active is True

    # After idle_ttl_seconds (15s elapsed), it should NOT be purged yet because active is True
    now[0] += 15
    with store._lock:
        store._purge_locked(now[0])
    assert conversation.conversation_id in store._items

    # After active_ttl_seconds (35s elapsed total), it SHOULD be purged as abandoned
    now[0] += 20
    with store._lock:
        store._purge_locked(now[0])
    assert conversation.conversation_id not in store._items


def test_conversation_store_evicts_oldest_inactive_at_capacity() -> None:
    from local_ai_hub.conversations import ConversationStore

    now = [100.0]
    store = ConversationStore(idle_ttl_seconds=1000, max_conversations=3, clock=lambda: now[0])
    c1 = store.start({"model": "m"})
    now[0] += 1
    c2 = store.start({"model": "m"})
    now[0] += 1
    c3 = store.start({"model": "m"})
    assert len(store._items) == 3

    # Adding a 4th conversation should evict c1 (oldest inactive)
    now[0] += 1
    c4 = store.start({"model": "m"})
    assert len(store._items) == 3
    assert c1.conversation_id not in store._items
    assert c4.conversation_id in store._items


def test_conversation_store_refuses_capacity_when_all_conversations_are_active() -> None:
    from local_ai_hub.conversations import ConversationStore

    store = ConversationStore(idle_ttl_seconds=1000, max_conversations=1)
    active = store.start({"model": "m"})
    reserved, error = store.reserve(active.conversation_id)

    assert reserved is active
    assert error == ""
    rejected = store.start({"model": "m"})

    assert rejected is None
    assert store._items[active.conversation_id] is active
    assert active.active is True


def test_conversation_store_start_reserved_is_protected_from_competing_start() -> None:
    from local_ai_hub.conversations import ConversationStore

    store = ConversationStore(idle_ttl_seconds=1000, max_conversations=1)
    reserved = store.start_reserved({"model": "m"})

    competing = store.start({"model": "m"})

    assert reserved is not None
    assert reserved.active is True
    assert competing is None
    assert store._items[reserved.conversation_id] is reserved


def test_service_rejects_conversation_start_at_capacity_without_generating() -> None:
    from local_ai_hub.conversations import ConversationStore
    from local_ai_hub.services import LocalAIServices

    services = object.__new__(LocalAIServices)
    services.config = {"token_saving": {"max_local_input_tokens": 4000}}
    services.conversations = ConversationStore(idle_ttl_seconds=1000, max_conversations=1)
    active = services.conversations.start({"model": "m"})
    services.conversations.reserve(active.conversation_id)
    generated: list[bool] = []

    def fake_generate(*args, **kwargs):
        generated.append(True)
        return {"success": True, "text": "unexpected"}

    services._generate = fake_generate
    result = services._start_conversation(
        prompt="question", route={"model": "m"}, system="system",
        max_tokens=32, temperature=0.0, source="delegate:general", priority=0,
    )

    assert result == {
        "success": False,
        "conversation_id": "",
        "error": "conversation capacity reached",
        "terminal": True,
        "retryable": False,
        "in_progress": False,
    }
    assert generated == []
    assert services.conversations._items[active.conversation_id] is active
    assert active.active is True


def test_service_does_not_report_success_when_conversation_is_lost_during_generation() -> None:
    from local_ai_hub.conversations import ConversationStore
    from local_ai_hub.services import LocalAIServices

    class LostConversationStore(ConversationStore):
        def complete(self, conversation_id, user_text, assistant_text):
            return False

    services = object.__new__(LocalAIServices)
    services.config = {"token_saving": {"max_local_input_tokens": 4000}}
    services.conversations = LostConversationStore(idle_ttl_seconds=1000, max_turns=2)
    conversation = services.conversations.start({
        "model": "m", "system": "system", "max_tokens": 32,
        "temperature": 0.0, "source": "delegate:general", "priority": 0,
        "route": {"model": "m"},
    })
    services._generate = lambda *args, **kwargs: {"success": True, "text": "answer"}

    result = services.continue_conversation(
        {"conversation_id": conversation.conversation_id, "task": "question"}
    )

    assert result["success"] is False
    assert result["conversation_id"] == conversation.conversation_id
    assert result["error"] == "conversation expired or was lost while model was running"
    assert result["terminal"] is True
    assert result["retryable"] is False


def test_service_marks_expired_conversations_terminal_and_running_ones_retryable() -> None:
    from local_ai_hub.conversations import ConversationStore
    from local_ai_hub.services import LocalAIServices

    now = [100.0]
    store = ConversationStore(idle_ttl_seconds=5, clock=lambda: now[0])
    services = object.__new__(LocalAIServices)
    services.conversations = store

    expired = store.start({"model": "fast"})
    now[0] += 6
    expired_result = services.continue_conversation(
        {"conversation_id": expired.conversation_id, "task": "follow-up"}
    )

    assert expired_result == {
        "success": False,
        "conversation_id": expired.conversation_id,
        "error": "conversation not found",
        "terminal": True,
        "retryable": False,
        "in_progress": False,
    }

    running = store.start({"model": "fast"})
    reserved, error = store.reserve(running.conversation_id)
    assert reserved is running
    assert error == ""
    running_result = services.continue_conversation(
        {"conversation_id": running.conversation_id, "task": "competing follow-up"}
    )

    assert running_result == {
        "success": False,
        "conversation_id": running.conversation_id,
        "error": "conversation is already running",
        "terminal": False,
        "retryable": True,
        "in_progress": True,
    }


def test_services_aborts_active_conversation_on_exception() -> None:
    import pytest
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

    def crashing_generate(*args, **kwargs):
        raise RuntimeError("simulated model crash")

    services._generate = crashing_generate

    with pytest.raises(RuntimeError, match="simulated model crash"):
        services.delegate({"task": "hello", "conversation": True})

    # Conversation should have been discarded on start exception
    assert len(services.conversations._items) == 0

    # Test continue_conversation exception
    services._generate = lambda *args, **kwargs: {"success": True, "text": "init"}
    res = services.delegate({"task": "hello", "conversation": True})
    cid = res["conversation_id"]

    # Now make it crash on continue
    services._generate = crashing_generate
    with pytest.raises(RuntimeError, match="simulated model crash"):
        services.continue_conversation({"conversation_id": cid, "task": "next"})

    # The conversation should NOT be locked in active state
    conv, err = services.conversations.reserve(cid)
    assert err == ""
    assert conv is not None
    assert conv.active is True
