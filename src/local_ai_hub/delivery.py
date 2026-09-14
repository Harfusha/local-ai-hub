from __future__ import annotations

from typing import Any


_MODES = {"sync", "async", "auto"}
_MIN_AUTO_SAMPLES = 10


def decide_delivery(
    delivery: str,
    *,
    latency_budget_ms: float = 0.0,
    observed_p95_ms: float = 0.0,
    samples: int = 0,
) -> dict[str, Any]:
    """Choose foreground or durable delivery without guessing on sparse history."""
    mode = str(delivery or "sync").strip().lower()
    if mode not in _MODES:
        raise ValueError("delivery must be sync, async, or auto")
    p95 = max(0.0, float(observed_p95_ms or 0.0))
    count = max(0, int(samples or 0))
    if mode == "sync":
        return {"mode": "sync", "reason": "sync_requested", "observed_p95_ms": p95, "samples": count}
    if mode == "async":
        return {"mode": "async", "reason": "async_requested", "observed_p95_ms": p95, "samples": count}
    budget = max(0.0, float(latency_budget_ms or 0.0))
    if budget <= 0:
        return {"mode": "sync", "reason": "latency_budget_not_provided", "observed_p95_ms": p95, "samples": count}
    if count < _MIN_AUTO_SAMPLES:
        return {"mode": "sync", "reason": "insufficient_latency_history", "observed_p95_ms": p95, "samples": count}
    if p95 > budget:
        return {"mode": "async", "reason": "p95_latency_budget_exceeded", "observed_p95_ms": p95, "samples": count}
    return {"mode": "sync", "reason": "p95_within_latency_budget", "observed_p95_ms": p95, "samples": count}
