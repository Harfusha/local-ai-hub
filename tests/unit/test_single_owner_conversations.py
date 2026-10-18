from __future__ import annotations

import pytest

from local_ai_hub.conversations import Conversation, ConversationStore


class _Clock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


@pytest.mark.parametrize("retired_value", [None, False, ""])
def test_conversation_settings_reject_retired_tenant_by_presence(retired_value):
    with pytest.raises(ValueError, match="retired conversation settings field: tenant"):
        Conversation(conversation_id="c1", settings={"tenant": retired_value})
    # Model configuration is opaque domain data, even when it contains a retired word.
    nested = Conversation(conversation_id="c1", settings={"model": {"tenant": retired_value}})
    assert nested.settings["model"] == {"tenant": retired_value}
    store = ConversationStore()
    with pytest.raises(ValueError, match="retired conversation settings field: tenant"):
        store.start({"tenant": retired_value})
    stored = store.start({"model": {"tenant": retired_value}})
    assert stored is not None and stored.settings["model"] == {"tenant": retired_value}


def test_conversation_constructor_is_keyword_only_and_settings_must_be_mapping():
    with pytest.raises(TypeError):
        Conversation("c1", "legacy-tenant", {"task": "value"})
    with pytest.raises(TypeError, match="settings must be a mapping"):
        Conversation(conversation_id="c1", settings="legacy-tenant")
    with pytest.raises(ValueError, match="retired conversation messages field: tenant"):
        Conversation(conversation_id="c1", settings={}, messages=[{"role": "user", "tenant": "legacy"}])


def test_conversation_store_preserves_scope_settings_messages_and_turn_limit():
    store = ConversationStore(max_turns=1)
    settings = {
        "root": "C:/repo",
        "repository_id": "repo-1",
        "task_id": "task-1",
        "session_id": "session-1",
        "clone_id": "clone-1",
        "worktree_id": "worktree-1",
        "branch": "main",
        "model": "configured-model",
        "system": "configured system text",
    }
    conversation = store.start_reserved(settings)
    assert conversation is not None
    assert conversation.settings == settings
    assert conversation.to_dict()["settings"] == settings
    assert "tenant" not in conversation.to_dict()

    reserved, error = store.reserve(conversation.conversation_id)
    assert reserved is None
    assert error == "conversation is already running"
    assert store.complete(conversation.conversation_id, "user\x00 text", "assistant text") is True
    assert conversation.messages == [
        {"role": "user", "content": "user text"},
        {"role": "assistant", "content": "assistant text"},
    ]

    reserved, error = store.reserve(conversation.conversation_id)
    assert reserved is None
    assert error == "conversation turn limit reached"
    assert store.active_count() == 0


def test_conversation_store_abort_discard_capacity_and_ttl():
    clock = _Clock()
    store = ConversationStore(
        idle_ttl_seconds=5,
        active_ttl_seconds=10,
        max_conversations=1,
        clock=clock,
    )
    first = store.start_reserved({"task_id": "task-1"})
    assert first is not None
    assert store.abort(first.conversation_id) is True
    assert first.active is False
    assert store.complete(first.conversation_id, "cancelled", "ignored") is False

    replacement = store.start({"task_id": "task-2"})
    assert replacement is not None
    assert store.count() == 1
    assert replacement.conversation_id != first.conversation_id

    clock.value = 6
    store.reserve("missing")
    assert store.count() == 0
    assert store.start({"session_id": "session-2"}) is not None
    store.discard(next(iter(store._items)))
    assert store.count() == 0


def test_conversation_store_rejects_retired_keywords_for_all_operations():
    store = ConversationStore()
    with pytest.raises(TypeError):
        store.start({}, tenant=None)
    with pytest.raises(TypeError):
        store.start_reserved({}, tenant=False)
    with pytest.raises(TypeError):
        store.reserve("c1", tenant="")
    with pytest.raises(TypeError):
        store.complete("c1", "user", "assistant", tenant=None)
    with pytest.raises(TypeError):
        store.abort("c1", tenant=False)
    with pytest.raises(TypeError):
        store.discard("c1", tenant="")
