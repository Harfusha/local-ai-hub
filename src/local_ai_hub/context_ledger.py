"""Bounded metadata-only ledger for agent context pressure."""

from __future__ import annotations

from collections import Counter, deque
from threading import Lock
from typing import Any


class ContextLedger:
    """Track token pressure without retaining prompts, source, or command text."""

    def __init__(self, *, max_entries: int = 512) -> None:
        self._entries: deque[dict[str, Any]] = deque(maxlen=max(1, int(max_entries)))
        self._totals: Counter[str] = Counter()
        self._outcomes: Counter[str] = Counter()
        self._lock = Lock()

    def record(
        self,
        *,
        tool: str,
        operation: str,
        request_tokens: int = 0,
        response_tokens: int = 0,
        saved_tokens: int = 0,
        cache_outcome: str = "",
        result_id: str = "",
        session_id: str = "",
    ) -> None:
        entry = {
            "tool": str(tool or "")[:64],
            "operation": str(operation or "default")[:64],
            "request_tokens": max(0, int(request_tokens or 0)),
            "response_tokens": max(0, int(response_tokens or 0)),
            "saved_tokens": max(0, int(saved_tokens or 0)),
            "cache_outcome": str(cache_outcome or "none")[:24],
            "result_id": str(result_id or "")[:32],
        }
        with self._lock:
            if len(self._entries) == self._entries.maxlen:
                evicted = self._entries[0]
                self._totals.subtract({key: evicted[key] for key in ("request_tokens", "response_tokens", "saved_tokens")})
                if evicted["cache_outcome"]:
                    self._outcomes[evicted["cache_outcome"]] -= 1
                    if self._outcomes[evicted["cache_outcome"]] <= 0:
                        del self._outcomes[evicted["cache_outcome"]]
            self._entries.append(entry)
            self._totals.update({key: entry[key] for key in ("request_tokens", "response_tokens", "saved_tokens")})
            if entry["cache_outcome"]:
                self._outcomes[entry["cache_outcome"]] += 1

    def snapshot(self, *, limit: int = 8) -> dict[str, Any]:
        with self._lock:
            entries = list(self._entries)[-max(1, min(int(limit), len(self._entries))):]
            return {
                "entries": len(self._entries),
                "totals": dict(self._totals),
                "cache_outcomes": dict(self._outcomes),
                "last": dict(entries[-1]) if entries else {},
                "recent": [dict(entry) for entry in entries],
            }

    def adaptive_profile(self, requested: str = "compact") -> str:
        profile = str(requested or "compact").strip().lower()
        if profile in {"minimal", "standard", "debug", "delta"}:
            return profile
        with self._lock:
            recent = list(self._entries)[-8:]
        if len(recent) >= 3 and sum(item["response_tokens"] for item in recent) >= 240:
            hits = sum(item["cache_outcome"] in {"hit", "reused"} for item in recent)
            if hits >= max(2, len(recent) // 2):
                return "minimal"
        return "compact"
