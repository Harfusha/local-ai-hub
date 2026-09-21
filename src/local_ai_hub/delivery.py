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
    queue_age_ms: float = 0.0,
    max_queue_age_ms: float = 0.0,
) -> dict[str, Any]:
    """Choose foreground or durable delivery without guessing on sparse history."""
    mode = str(delivery or "sync").strip().lower()
    if mode not in _MODES:
        raise ValueError("delivery must be sync, async, or auto")
    p95 = max(0.0, float(observed_p95_ms or 0.0))
    count = max(0, int(samples or 0))
    queue_age = max(0.0, float(queue_age_ms or 0.0))
    queue_limit = max(0.0, float(max_queue_age_ms or 0.0))

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
    budget = max(0.0, float(latency_budget_ms or 0.0))
    if budget <= 0:
        return finish({"mode": "sync", "reason": "latency_budget_not_provided", "observed_p95_ms": p95, "samples": count})
    if count < _MIN_AUTO_SAMPLES:
        return finish({"mode": "sync", "reason": "insufficient_latency_history", "observed_p95_ms": p95, "samples": count})
    if p95 > budget:
        return finish({"mode": "async", "reason": "p95_latency_budget_exceeded", "observed_p95_ms": p95, "samples": count})
    return finish({"mode": "sync", "reason": "p95_within_latency_budget", "observed_p95_ms": p95, "samples": count})
