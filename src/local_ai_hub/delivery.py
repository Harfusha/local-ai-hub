from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any


_MODES = {"sync", "async", "auto"}
_MIN_AUTO_SAMPLES = 10


def _safe_nonnegative_float(value: Any) -> float:
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not math.isfinite(parsed) or parsed < 0.0:
        return 0.0
    return parsed


def _safe_nonnegative_int(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def is_valid_delivery_mode(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, str):
        return False
    mode = value.replace("\x00", "").strip().lower()
    return mode in _MODES


def is_async_delivery(decision: Mapping[str, Any] | object) -> bool:
    if not isinstance(decision, Mapping):
        return False
    return str(decision.get("mode") or "").strip().lower() == "async"


def is_bypass_delivery(decision: Mapping[str, Any] | object) -> bool:
    if not isinstance(decision, Mapping):
        return False
    return str(decision.get("mode") or "").strip().lower() == "bypass"


def decide_delivery(
    delivery: str,
    *,
    latency_budget_ms: float = 0.0,
    observed_p95_ms: float = 0.0,
    samples: int = 0,
    queue_age_ms: float = 0.0,
    max_queue_age_ms: float = 0.0,
) -> dict[str, Any]:
    """Choose foreground or durable delivery without guessing on sparse history."""
    if isinstance(delivery, bool):
        raise ValueError("delivery must be sync, async, or auto")
    mode = str(delivery or "sync").replace("\x00", "").strip().lower() or "sync"
    if mode not in _MODES:
        raise ValueError("delivery must be sync, async, or auto")
    p95 = _safe_nonnegative_float(observed_p95_ms)
    count = _safe_nonnegative_int(samples)
    queue_age = _safe_nonnegative_float(queue_age_ms)
    queue_limit = _safe_nonnegative_float(max_queue_age_ms)

    def finish(result: dict[str, Any]) -> dict[str, Any]:
        if queue_age or queue_limit:
            result["queue_age_ms"] = queue_age
        return result

    if mode == "sync":
        return finish({"mode": "sync", "reason": "sync_requested", "observed_p95_ms": p95, "samples": count})
    if mode == "async":
        return finish({"mode": "async", "reason": "async_requested", "observed_p95_ms": p95, "samples": count})
    if queue_limit > 0 and queue_age > queue_limit:
        return finish({
            "mode": "bypass",
            "reason": "queue_age_budget_exceeded",
            "observed_p95_ms": p95,
            "samples": count,
            "queue_age_ms": queue_age,
            "max_queue_age_ms": queue_limit,
        })
    budget = _safe_nonnegative_float(latency_budget_ms)
    if budget <= 0:
        return finish({"mode": "sync", "reason": "latency_budget_not_provided", "observed_p95_ms": p95, "samples": count})
    if count < _MIN_AUTO_SAMPLES:
        return finish({"mode": "sync", "reason": "insufficient_latency_history", "observed_p95_ms": p95, "samples": count})
    if p95 > budget:
        return finish({"mode": "async", "reason": "p95_latency_budget_exceeded", "observed_p95_ms": p95, "samples": count})
    return finish({"mode": "sync", "reason": "p95_within_latency_budget", "observed_p95_ms": p95, "samples": count})
