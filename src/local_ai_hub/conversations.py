from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any


@dataclass
class Conversation:
    conversation_id: str
    tenant: str
    settings: dict[str, Any]
    messages: list[dict[str, str]] = field(default_factory=list)
    active: bool = False
    updated_at: float = 0.0


class ConversationStore:
    """Bounded process-memory conversation state. Never writes transcripts to disk."""

    def __init__(
        self,
        *,
        idle_ttl_seconds: float = 900.0,
        active_ttl_seconds: float = 1800.0,
        max_turns: int = 12,
        max_conversations: int = 1000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.idle_ttl_seconds = max(1.0, float(idle_ttl_seconds))
        self.active_ttl_seconds = max(self.idle_ttl_seconds, float(active_ttl_seconds))
        self.max_turns = max(1, int(max_turns))
        self.max_conversations = max(1, int(max_conversations))
        self._clock = clock
        self._items: dict[str, Conversation] = {}
        self._lock = threading.Lock()

    def start(self, tenant: str, settings: dict[str, Any]) -> Conversation:
        now = self._clock()
        conversation = Conversation(
            conversation_id=uuid.uuid4().hex,
            tenant=str(tenant),
            settings=dict(settings),
            updated_at=now,
        )
        with self._lock:
            self._purge_locked(now)
            if len(self._items) >= self.max_conversations:
                oldest_cid = min(self._items.keys(), key=lambda k: self._items[k].updated_at)
                self._items.pop(oldest_cid, None)
            self._items[conversation.conversation_id] = conversation
        return conversation

    def reserve(self, conversation_id: str, tenant: str) -> tuple[Conversation | None, str]:
        now = self._clock()
        with self._lock:
            self._purge_locked(now)
            conversation = self._items.get(str(conversation_id))
            if conversation is None or conversation.tenant != str(tenant):
                return None, "conversation not found"
            if conversation.active:
                return None, "conversation is already running"
            if len(conversation.messages) // 2 >= self.max_turns:
                return None, "conversation turn limit reached"
            conversation.active = True
            conversation.updated_at = now
            return conversation, ""

    def complete(self, conversation_id: str, tenant: str, user_text: str, assistant_text: str) -> bool:
        with self._lock:
            conversation = self._owned_active_locked(conversation_id, tenant)
            if conversation is None:
                return False
            conversation.messages.extend((
                {"role": "user", "content": str(user_text)},
                {"role": "assistant", "content": str(assistant_text)},
            ))
            conversation.active = False
            conversation.updated_at = self._clock()
            return True

    def abort(self, conversation_id: str, tenant: str) -> bool:
        with self._lock:
            conversation = self._owned_active_locked(conversation_id, tenant)
            if conversation is None:
                return False
            conversation.active = False
            conversation.updated_at = self._clock()
            return True

    def discard(self, conversation_id: str, tenant: str) -> None:
        with self._lock:
            conversation = self._items.get(str(conversation_id))
            if conversation is not None and conversation.tenant == str(tenant):
                self._items.pop(conversation.conversation_id, None)

    def _owned_active_locked(self, conversation_id: str, tenant: str) -> Conversation | None:
        conversation = self._items.get(str(conversation_id))
        if conversation is None or conversation.tenant != str(tenant) or not conversation.active:
            return None
        return conversation

    def _purge_locked(self, now: float) -> None:
        stale = [
            conversation_id
            for conversation_id, conversation in self._items.items()
            if (not conversation.active and now - conversation.updated_at > self.idle_ttl_seconds)
            or (conversation.active and now - conversation.updated_at > self.active_ttl_seconds)
        ]
        for conversation_id in stale:
            self._items.pop(conversation_id, None)

        if len(self._items) >= self.max_conversations:
            inactive = sorted(
                (c.updated_at, cid)
                for cid, c in self._items.items()
                if not c.active
            )
            for _, cid in inactive:
                self._items.pop(cid, None)
                if len(self._items) < self.max_conversations:
                    break
