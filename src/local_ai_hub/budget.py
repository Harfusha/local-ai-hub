from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Any


TRUNCATION_MARKER = "\n\n[... context omitted to fit local budget ...]\n"


def estimate_tokens(text: str) -> int:
    """Conservative tokenizer-free estimate suitable for prompt budgeting/telemetry."""
    if not text:
        return 0
    return max(1, math.ceil(len(text.encode("utf-8")) / 3.4))


def chars_for_tokens(tokens: int) -> int:
    return max(0, int(tokens * 3.4))


@dataclass(frozen=True)
class PackedText:
    text: str
    estimated_tokens: int
    truncated: bool
    original_tokens: int


class RootFamilyBudget:
    """Small in-process admission guard for root-family fanout and token use."""

    def __init__(self, default_limit: int = 0, *, max_active_scopes: int = 1) -> None:
        self.default_limit = max(0, int(default_limit))
        self.max_active_scopes = max(1, int(max_active_scopes))
        self._used: dict[str, int] = {}
        self._scopes: dict[str, set[str]] = {}
        self._lock = threading.RLock()

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
        key = str(family or "").strip() or "default"
        amount = max(0, int(input_tokens or 0)) + max(0, int(output_tokens or 0))
        cap = self.default_limit if limit is None else max(0, int(limit))
        with self._lock:
            used = self._used.get(key, 0)
            scopes = self._scopes.setdefault(key, set())
            if scope and scope in scopes:
                return {"status": "coalesced", "family": key, "used": used, "remaining": max(0, cap - used), "scope": scope}
            if cap and used + amount > cap:
                return {"status": "rejected", "reason": "root_family_budget_exceeded", "family": key, "used": used, "remaining": max(0, cap - used), "retryable": False}
            if scope and len(scopes) >= self.max_active_scopes:
                return {"status": "rejected", "reason": "fanout_scope_limit_exceeded", "family": key, "used": used, "remaining": max(0, cap - used), "retryable": True}
            self._used[key] = used + amount
            if scope:
                scopes.add(scope)
            return {"status": "accepted", "family": key, "used": self._used[key], "remaining": max(0, cap - self._used[key]) if cap else None, "task_id": str(task_id or "")[:96]}

    def release(self, family: str, *, tokens: int = 0, scope: str = "") -> dict[str, Any]:
        key = str(family or "").strip() or "default"
        with self._lock:
            self._used[key] = max(0, self._used.get(key, 0) - max(0, int(tokens or 0)))
            if scope:
                self._scopes.setdefault(key, set()).discard(scope)
            return {"status": "released", "family": key, "used": self._used[key]}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"families": {key: {"used": used, "active_scopes": len(self._scopes.get(key, set()))} for key, used in self._used.items()}}


def fit_text(text: str, max_tokens: int, *, preserve_tail: bool = True) -> PackedText:
    max_tokens = max(64, int(max_tokens))
    original = estimate_tokens(text)
    if original <= max_tokens:
        return PackedText(text=text, estimated_tokens=original, truncated=False, original_tokens=original)

    # Token estimates use UTF-8 bytes, so character slicing can overshoot badly
    # for non-ASCII text. Keep the output within the same byte budget.
    budget = max(1, int(max_tokens * 3.4))
    marker = TRUNCATION_MARKER
    marker_bytes = len(marker.encode("utf-8"))
    usable = max(0, budget - marker_bytes)

    def prefix(value: str, limit: int) -> str:
        return value.encode("utf-8")[:limit].decode("utf-8", errors="ignore")

    def suffix(value: str, limit: int) -> str:
        return value.encode("utf-8")[-limit:].decode("utf-8", errors="ignore")

    if preserve_tail and usable >= 800:
        head = int(usable * 0.72)
        fitted = prefix(text, head) + marker + suffix(text, usable - head)
    else:
        fitted = prefix(text, usable) + marker
    return PackedText(
        text=fitted,
        estimated_tokens=estimate_tokens(fitted),
        truncated=True,
        original_tokens=original,
    )
