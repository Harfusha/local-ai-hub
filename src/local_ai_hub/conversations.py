from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import math
import threading
import time
from typing import Any
import uuid


_RETIRED_TENANT_FIELDS = frozenset({"tenant", "tenant_id", "tenant_key", "tenant_scope"})
_CONVERSATION_CONTROL_CONTAINERS = frozenset({"metadata", "provenance", "control"})


def _clean_str(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    return str(value).replace("\x00", "")


def _safe_positive_float(value: Any, default: float, *, minimum: float = 1.0) -> float:
    if value is None or isinstance(value, bool):
        return max(minimum, default)
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return max(minimum, default)
    if not math.isfinite(parsed):
        return max(minimum, default)
    return max(minimum, parsed)


def _safe_nonnegative_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(parsed) or parsed < 0.0:
        return default
    return parsed


def _safe_positive_int(value: Any, default: int) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        return max(1, int(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _reject_retired_tenant_fields(value: Any, label: str) -> None:
    seen: set[int] = set()
    inspected = 0

    def inspect_mapping(mapping: Mapping[str, Any]) -> None:
        nonlocal inspected
        present = _RETIRED_TENANT_FIELDS.intersection(mapping)
        if present:
            raise ValueError(f"retired {label} field: {sorted(present)[0]}")
        identity = id(mapping)
        if identity in seen:
            return
        seen.add(identity)
        inspected += len(mapping)
        if inspected > 4096:
            raise ValueError(f"{label} exceeds supported item limit")
        # These are declared control envelopes. Message content and nested domain
        # objects remain opaque, even when their data uses retired words.
        for key in _CONVERSATION_CONTROL_CONTAINERS:
            child = mapping.get(key)
            if isinstance(child, Mapping):
                inspect_direct_mapping(child)

    def inspect_direct_mapping(mapping: Mapping[str, Any]) -> None:
        nonlocal inspected
        present = _RETIRED_TENANT_FIELDS.intersection(mapping)
        if present:
            raise ValueError(f"retired {label} field: {sorted(present)[0]}")
        identity = id(mapping)
        if identity in seen:
            return
        seen.add(identity)
        inspected += len(mapping)
        if inspected > 4096:
            raise ValueError(f"{label} exceeds supported item limit")

    if isinstance(value, Mapping):
        inspect_mapping(value)
    elif isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in seen:
            return
        seen.add(identity)
        inspected += len(value)
        if inspected > 4096:
            raise ValueError(f"{label} exceeds supported item limit")
        # For messages, inspect each message envelope and its one direct layer of
        # declared control dictionaries. Never traverse content/tool/domain data.
        for item in value:
            if isinstance(item, Mapping):
                inspect_mapping(item)


@dataclass(kw_only=True)
class Conversation:
    conversation_id: str
    settings: dict[str, Any]
    messages: list[dict[str, str]] = field(default_factory=list)
    active: bool = False
    updated_at: float = 0.0

    def __post_init__(self) -> None:
        self.conversation_id = _clean_str(self.conversation_id).strip()
        if not isinstance(self.settings, Mapping):
            raise TypeError("conversation settings must be a mapping")
        _reject_retired_tenant_fields(self.settings, "conversation settings")
        self.settings = dict(self.settings)
        _reject_retired_tenant_fields(self.messages, "conversation messages")
        self.messages = (
            [dict(item) for item in self.messages if isinstance(item, Mapping)]
            if isinstance(self.messages, (list, tuple))
            else []
        )
        self.active = bool(self.active)
        self.updated_at = _safe_nonnegative_float(self.updated_at, 0.0)

    def turn_count(self) -> int:
        return len(self.messages) // 2

    def is_empty(self) -> bool:
        return len(self.messages) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "settings": dict(self.settings),
            "messages": [dict(item) for item in self.messages],
            "active": self.active,
            "updated_at": self.updated_at,
            "turn_count": self.turn_count(),
        }


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
        self.idle_ttl_seconds = _safe_positive_float(idle_ttl_seconds, 900.0, minimum=1.0)
        self.active_ttl_seconds = _safe_positive_float(
            active_ttl_seconds,
            max(self.idle_ttl_seconds, 1800.0),
            minimum=self.idle_ttl_seconds,
        )
        self.max_turns = _safe_positive_int(max_turns, 12)
        self.max_conversations = _safe_positive_int(max_conversations, 1000)
        self._clock = clock if callable(clock) else time.monotonic
        self._items: dict[str, Conversation] = {}
        self._lock = threading.Lock()

    def count(self) -> int:
        with self._lock:
            return len(self._items)

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for item in self._items.values() if item.active)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def start(self, settings: dict[str, Any]) -> Conversation | None:
        return self._start(settings, active=False)

    def start_reserved(self, settings: dict[str, Any]) -> Conversation | None:
        """Create and reserve a conversation atomically before it becomes visible."""
        return self._start(settings, active=True)

    def _start(self, settings: dict[str, Any], *, active: bool) -> Conversation | None:
        now = self._clock()
        conversation = Conversation(
            conversation_id=uuid.uuid4().hex,
            settings=settings,
            active=active,
            updated_at=now,
        )
        with self._lock:
            self._purge_locked(now)
            if len(self._items) >= self.max_conversations:
                inactive = [
                    (item.updated_at, conversation_id)
                    for conversation_id, item in self._items.items()
                    if not item.active
                ]
                if not inactive:
                    return None
                _, oldest_cid = min(inactive)
                self._items.pop(oldest_cid, None)
            self._items[conversation.conversation_id] = conversation
        return conversation

    def reserve(self, conversation_id: str) -> tuple[Conversation | None, str]:
        now = self._clock()
        cid = _clean_str(conversation_id).strip()
        with self._lock:
            self._purge_locked(now)
            conversation = self._items.get(cid)
            if conversation is None:
                return None, "conversation not found"
            if conversation.active:
                return None, "conversation is already running"
            if len(conversation.messages) // 2 >= self.max_turns:
                return None, "conversation turn limit reached"
            conversation.active = True
            conversation.updated_at = now
            return conversation, ""

    def complete(self, conversation_id: str, user_text: str, assistant_text: str) -> bool:
        with self._lock:
            now = self._clock()
            self._purge_locked(now)
            conversation = self._owned_active_locked(conversation_id)
            if conversation is None:
                return False
            conversation.messages.extend((
                {"role": "user", "content": _clean_str(user_text)},
                {"role": "assistant", "content": _clean_str(assistant_text)},
            ))
            conversation.active = False
            conversation.updated_at = now
            return True

    def abort(self, conversation_id: str) -> bool:
        with self._lock:
            now = self._clock()
            self._purge_locked(now)
            conversation = self._owned_active_locked(conversation_id)
            if conversation is None:
                return False
            conversation.active = False
            conversation.updated_at = now
            return True

    def discard(self, conversation_id: str) -> None:
        cid = _clean_str(conversation_id).strip()
        with self._lock:
            conversation = self._items.get(cid)
            if conversation is not None:
                self._items.pop(conversation.conversation_id, None)

    def _owned_active_locked(self, conversation_id: str) -> Conversation | None:
        cid = _clean_str(conversation_id).strip()
        conversation = self._items.get(cid)
        if conversation is None or not conversation.active:
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
