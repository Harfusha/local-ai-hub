from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Any


TRUNCATION_MARKER = "\n\n[... context omitted to fit local budget ...]\n"


def _safe_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def estimate_tokens(text: str) -> int:
    """Conservative tokenizer-free estimate suitable for prompt budgeting/telemetry."""
    if not text:
        return 0
    raw = str(text)
    if not raw:
        return 0
    return max(1, math.ceil(len(raw.encode("utf-8", errors="replace")) / 3.4))


def chars_for_tokens(tokens: int) -> int:
    safe_tok = _safe_int(tokens, 0)
    if safe_tok <= 0:
        return 0
    return max(0, int(safe_tok * 3.4))


@dataclass(frozen=True)
class PackedText:
    text: str
    estimated_tokens: int
    truncated: bool
    original_tokens: int

    def __post_init__(self) -> None:
        clean_text = "" if self.text is None else str(self.text).replace("\x00", "")
        est = max(0, _safe_int(self.estimated_tokens, 0))
        orig = max(0, _safe_int(self.original_tokens, 0))
        object.__setattr__(self, "text", clean_text)
        object.__setattr__(self, "estimated_tokens", est)
        object.__setattr__(self, "truncated", bool(self.truncated))
        object.__setattr__(self, "original_tokens", orig)

    def is_empty(self) -> bool:
        return not bool(self.text)

    def saved_tokens(self) -> int:
        return max(0, self.original_tokens - self.estimated_tokens)

    def compression_ratio(self) -> float:
        if self.original_tokens <= 0:
            return 1.0
        return round(min(1.0, max(0.0, self.estimated_tokens / self.original_tokens)), 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "estimated_tokens": self.estimated_tokens,
            "truncated": self.truncated,
            "original_tokens": self.original_tokens,
        }


class RootFamilyBudget:
    """Small in-process admission guard for root-family fanout and token use."""

    def __init__(self, default_limit: int = 0, *, max_active_scopes: int = 1) -> None:
        self.default_limit = max(0, _safe_int(default_limit, 0))
        self.max_active_scopes = max(1, _safe_int(max_active_scopes, 1))
        self._used: dict[str, int] = {}
        self._scopes: dict[str, set[str]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _clean(val: Any) -> str:
        return str(val or "").replace("\x00", "").strip()

    def reserve(
        self,
        family: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        limit: int | None = None,
        task_id: str = "",
        scope: str = "",
    ) -> dict[str, Any]:
        key = self._clean(family) or "default"
        clean_scope = self._clean(scope)
        clean_task = self._clean(task_id)[:96]
        amount = max(0, _safe_int(input_tokens, 0)) + max(0, _safe_int(output_tokens, 0))
        cap = self.default_limit if limit is None else max(0, _safe_int(limit, 0))
        with self._lock:
            used = self._used.get(key, 0)
            scopes = self._scopes.setdefault(key, set())
            if clean_scope and clean_scope in scopes:
                return {"status": "coalesced", "family": key, "used": used, "remaining": max(0, cap - used), "scope": clean_scope}
            if cap and used + amount > cap:
                return {"status": "rejected", "reason": "root_family_budget_exceeded", "family": key, "used": used, "remaining": max(0, cap - used), "retryable": False}
            if clean_scope and len(scopes) >= self.max_active_scopes:
                return {"status": "rejected", "reason": "fanout_scope_limit_exceeded", "family": key, "used": used, "remaining": max(0, cap - used), "retryable": True}
            self._used[key] = used + amount
            if clean_scope:
                scopes.add(clean_scope)
            return {"status": "accepted", "family": key, "used": self._used[key], "remaining": max(0, cap - self._used[key]) if cap else None, "task_id": clean_task}

    def release(self, family: str, *, tokens: int = 0, scope: str = "") -> dict[str, Any]:
        key = self._clean(family) or "default"
        clean_scope = self._clean(scope)
        with self._lock:
            self._used[key] = max(0, self._used.get(key, 0) - max(0, _safe_int(tokens, 0)))
            if clean_scope:
                self._scopes.setdefault(key, set()).discard(clean_scope)
            return {"status": "released", "family": key, "used": self._used[key]}

    def used_tokens(self, family: str) -> int:
        key = self._clean(family) or "default"
        with self._lock:
            return self._used.get(key, 0)

    def active_scopes_count(self, family: str) -> int:
        key = self._clean(family) or "default"
        with self._lock:
            return len(self._scopes.get(key, set()))

    def reset(self, family: str | None = None) -> None:
        with self._lock:
            if family is None:
                self._used.clear()
                self._scopes.clear()
            else:
                key = self._clean(family) or "default"
                self._used.pop(key, None)
                self._scopes.pop(key, None)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"families": {key: {"used": used, "active_scopes": len(self._scopes.get(key, set()))} for key, used in self._used.items()}}


def fit_text(text: str, max_tokens: int, *, preserve_tail: bool = True) -> PackedText:
    clean_text = "" if text is None else str(text)
    max_tokens = max(64, _safe_int(max_tokens, 64))
    original = estimate_tokens(clean_text)
    if original <= max_tokens:
        return PackedText(text=clean_text, estimated_tokens=original, truncated=False, original_tokens=original)

    # Token estimates use UTF-8 bytes, so character slicing can overshoot badly
    # for non-ASCII text. Keep the output within the same byte budget.
    budget = max(1, int(max_tokens * 3.4))
    marker = TRUNCATION_MARKER
    marker_bytes = len(marker.encode("utf-8"))
    usable = max(0, budget - marker_bytes)

    def prefix(value: str, limit: int) -> str:
        if limit <= 0:
            return ""
        return value.encode("utf-8", errors="replace")[:limit].decode("utf-8", errors="ignore")

    def suffix(value: str, limit: int) -> str:
        if limit <= 0:
            return ""
        return value.encode("utf-8", errors="replace")[-limit:].decode("utf-8", errors="ignore")

    if preserve_tail and usable >= 800:
        head = int(usable * 0.72)
        fitted = prefix(clean_text, head) + marker + suffix(clean_text, usable - head)
    else:
        fitted = prefix(clean_text, usable) + marker
    return PackedText(
        text=fitted,
        estimated_tokens=estimate_tokens(fitted),
        truncated=True,
        original_tokens=original,
    )
