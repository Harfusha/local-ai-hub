"""Privacy-safe, bounded adoption telemetry aggregates."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from contextlib import closing
import re
import threading
from typing import Any

from .sqlite_support import connect_sqlite


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_OUTCOMES = {"used", "bypassed", "blocked", "failed", "recommended", "fallback_used"}
_REASONS = {"policy", "unsupported", "unavailable", "timeout", "validation", "explicit_client_signal", "other"}
_FORBIDDEN = {"prompt", "source", "content", "path", "secret", "token", "password", "api_key"}


def _identifier(value: str, field: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _IDENTIFIER.fullmatch(normalized) or normalized in _FORBIDDEN:
        raise ValueError(f"{field} must be a safe normalized identifier")
    return normalized


def _duration_bucket(value: int | float | None) -> str | None:
    if value is None:
        return None
    value = max(0, int(value))
    if value <= 50: return "0-50ms"
    if value <= 250: return "51-250ms"
    if value <= 500: return "251-500ms"
    if value <= 2000: return "501ms-2s"
    return "2s+"


def _output_bucket(value: int | None) -> str | None:
    if value is None:
        return None
    value = max(0, int(value))
    if value <= 255: return "0-255B"
    if value <= 1023: return "256B-1KiB"
    if value <= 4095: return "1-4KiB"
    return "4KiB+"


class AdoptionMetricsStore:
    """Stores only daily low-cardinality aggregates; never raw tool payloads."""

    def __init__(self, state_dir: Path | str, *, retention_days: int = 35, max_actions: int = 256):
        self.path = Path(state_dir) / "adoption_metrics.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.retention_days = max(2, min(int(retention_days), 365))
        self.max_actions = max(16, min(int(max_actions), 1024))
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self):
        return connect_sqlite(self.path, timeout_seconds=5.0)

    def _initialize(self) -> None:
        with closing(self._connect()) as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("CREATE TABLE IF NOT EXISTS daily_adoption (day TEXT NOT NULL, tool TEXT NOT NULL, action TEXT NOT NULL, intent TEXT NOT NULL, outcome TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', latency_bucket TEXT NOT NULL DEFAULT '', output_bucket TEXT NOT NULL DEFAULT '', count INTEGER NOT NULL, PRIMARY KEY(day, tool, action, intent, outcome, reason, latency_bucket, output_bucket))")
            con.execute("CREATE TABLE IF NOT EXISTS adoption_actions (tool TEXT NOT NULL, action TEXT NOT NULL, last_seen_day TEXT NOT NULL, PRIMARY KEY(tool, action))")
            con.commit()

    def record(self, tool: str, action: str, intent: str, outcome: str, *, fallback_reason: str | None = None, duration_ms: int | float | None = None, output_size: int | None = None, now: datetime | None = None, **unsafe: Any) -> None:
        if unsafe:
            raise ValueError("telemetry fields must be safe normalized identifiers; prompts, source, content, secrets, and paths are rejected")
        tool = _identifier(tool, "tool")
        action = _identifier(action, "action")
        intent = _identifier(intent, "intent")
        outcome = _identifier(outcome, "outcome")
        if outcome not in _OUTCOMES:
            raise ValueError("outcome must be a supported aggregate")
        reason = ""
        if fallback_reason is not None:
            reason = str(fallback_reason or "").strip().lower()
            if reason not in _REASONS:
                raise ValueError("fallback reason must be safe fallback category")
        if outcome in {"blocked", "failed", "bypassed"} and not reason:
            reason = "other"
        current = now or datetime.now(timezone.utc)
        day = current.astimezone(timezone.utc).date().isoformat()
        latency = _duration_bucket(duration_ms)
        output = _output_bucket(output_size)
        with self._lock:
            with closing(self._connect()) as con:
                con.execute("INSERT INTO daily_adoption(day, tool, action, intent, outcome, reason, latency_bucket, output_bucket, count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1) ON CONFLICT(day, tool, action, intent, outcome, reason, latency_bucket, output_bucket) DO UPDATE SET count = count + 1", (day, tool, action, intent, outcome, reason, latency or "", output or ""))
                con.execute("INSERT INTO adoption_actions(tool, action, last_seen_day) VALUES (?, ?, ?) ON CONFLICT(tool, action) DO UPDATE SET last_seen_day = excluded.last_seen_day", (tool, action, day))
                con.execute("DELETE FROM daily_adoption WHERE day < ?", ((current.date() - timedelta(days=self.retention_days - 1)).isoformat(),))
                con.execute("DELETE FROM adoption_actions WHERE rowid NOT IN (SELECT rowid FROM adoption_actions ORDER BY last_seen_day DESC LIMIT ?)", (self.max_actions,))
                con.commit()

    def record_explicit_bypass(self, tool: str, action: str, intent: str, *, reason: str = "explicit_client_signal", now: datetime | None = None) -> None:
        self.record(tool, action, intent, "bypassed", fallback_reason=reason, now=now)

    def report(self, *, days: int = 7, now: datetime | None = None) -> dict[str, Any]:
        days = max(1, min(int(days), self.retention_days))
        current = now or datetime.now(timezone.utc)
        start = current.date() - timedelta(days=days - 1)
        start_text = start.isoformat()
        with self._lock:
            with closing(self._connect()) as con:
                rows = con.execute("SELECT day, tool, action, outcome, reason, latency_bucket, output_bucket, count FROM daily_adoption WHERE day >= ?", (start_text,)).fetchall()
                dormant = con.execute("SELECT tool, action FROM adoption_actions WHERE last_seen_day < ? ORDER BY tool, action", (start_text,)).fetchall()
        daily = { (start + timedelta(days=index)).isoformat(): {"day": (start + timedelta(days=index)).isoformat(), **{outcome: 0 for outcome in _OUTCOMES}} for index in range(days) }
        totals = {outcome: 0 for outcome in _OUTCOMES}
        reasons: dict[str, int] = {}; failures: dict[str, int] = {}; latency: dict[str, int] = {}; output: dict[str, int] = {}; actions: dict[tuple[str, str, str], int] = {}
        for day, tool, action, outcome, reason, latency_bucket, output_bucket, count in rows:
            count = int(count); daily[day][outcome] += count; totals[outcome] += count
            key = (tool, action, outcome); actions[key] = actions.get(key, 0) + count
            if outcome == "blocked" and reason: reasons[reason] = reasons.get(reason, 0) + count
            if outcome == "failed" and reason: failures[reason] = failures.get(reason, 0) + count
            if latency_bucket: latency[latency_bucket] = latency.get(latency_bucket, 0) + count
            if output_bucket: output[output_bucket] = output.get(output_bucket, 0) + count
        return {"days": days, "daily": list(daily.values()), "totals": totals, "routing_adoption": {"local_recommended": totals["recommended"], "local_used": totals["used"], "bypassed": totals["bypassed"], "fallback_used": totals["fallback_used"]}, "action_adoption": [{"tool": tool, "action": action, "outcome": outcome, "count": count} for (tool, action, outcome), count in sorted(actions.items())], "blocked_reasons": [{"reason": key, "count": value} for key, value in sorted(reasons.items())], "terminal_failures": [{"reason": key, "count": value} for key, value in sorted(failures.items())], "dormant_actions": [f"{tool}:{action}" for tool, action in dormant], "latency_buckets": [{"bucket": key, "count": value} for key, value in sorted(latency.items())], "output_size_buckets": [{"bucket": key, "count": value} for key, value in sorted(output.items())]}
