"""Reinforcement Learning and Outcome Feedback for Laya Decisions.

Collects downstream task verification receipts and execution outcomes to compute
reinforcement learning reward signals for Laya routing and context decisions.
Saves outcome pairs into state/laya_rl_feedback.jsonl for continuous adaptive tuning.
"""

from __future__ import annotations

import json
import logging
# import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LayaDecisionReceiptPair:
    """One Laya decision linked to downstream verification outcome."""

    decision_id: str
    task_id: str
    category: str
    suggestion: str
    chosen_options: tuple[str, ...]
    passed: bool
    error_count: int
    escalations: int
    reward: float
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["chosen_options"] = list(self.chosen_options)
        return d


def compute_outcome_reward(
    passed: bool,
    error_count: int = 0,
    escalations: int = 0,
    latency_ms: float = 0.0,
) -> float:
    """Calculate normalized reward scalar [-1.0, 1.0] from task verification receipts."""
    if not passed:
        # Penalize failed task verification
        return -1.0

    # Base reward for passing verification
    reward = 1.0

    # Subtract penalty for redundant escalations (e.g. failing indexed and falling back to RAG)
    if escalations > 0:
        reward -= min(0.6, 0.2 * escalations)

    # Subtract small penalty for non-zero errors during execution
    if error_count > 0:
        reward -= min(0.3, 0.1 * error_count)

    return max(-1.0, min(1.0, reward))


class LayaOutcomeRewardTracker:
    """Thread-safe tracker pairing Laya decisions with task verification receipts."""

    def __init__(self, log_path: str | Path | None = None) -> None:
        self.log_path = Path(log_path or "state/laya_rl_feedback.jsonl")
        self._lock = threading.Lock()
        self._active_decisions: dict[str, list[dict[str, Any]]] = {}

    def register_decision(
        self,
        task_id: str,
        decision_id: str,
        category: str,
        suggestion: str,
        options: Sequence[str] = (),
    ) -> None:
        """Register a decision made by Laya for an active task."""
        if not task_id or not decision_id:
            return
        with self._lock:
            self._active_decisions.setdefault(task_id, []).append({
                "decision_id": decision_id,
                "category": category,
                "suggestion": suggestion,
                "options": tuple(options),
                "timestamp": time.time(),
            })

    def record_receipt_outcome(
        self,
        task_id: str,
        passed: bool,
        error_count: int = 0,
        escalations: int = 0,
        latency_ms: float = 0.0,
    ) -> list[LayaDecisionReceiptPair]:
        """Attach task completion receipt to all associated Laya decisions."""
        with self._lock:
            decisions = self._active_decisions.pop(task_id, [])

        if not decisions:
            return []

        reward = compute_outcome_reward(
            passed=passed,
            error_count=error_count,
            escalations=escalations,
            latency_ms=latency_ms,
        )

        pairs: list[LayaDecisionReceiptPair] = []
        now = time.time()
        for d in decisions:
            pairs.append(LayaDecisionReceiptPair(
                decision_id=d["decision_id"],
                task_id=task_id,
                category=d["category"],
                suggestion=d["suggestion"],
                chosen_options=d["options"],
                passed=passed,
                error_count=error_count,
                escalations=escalations,
                reward=reward,
                timestamp=now,
            ))

        # Append to log file
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, open(self.log_path, "a", encoding="utf-8") as f:
                for p in pairs:
                    f.write(json.dumps(p.to_dict()) + "\n")
        except Exception as exc:
            logger.warning("Failed to persist Laya RL feedback: %s", exc)

        return pairs
