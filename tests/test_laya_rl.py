"""Tests for Laya Reinforcement Learning outcome feedback."""

import tempfile

from src.local_ai_hub.laya_rl import (
    LayaOutcomeRewardTracker,
    compute_outcome_reward,
)


def test_compute_outcome_reward():
    # Perfect run
    assert compute_outcome_reward(passed=True, error_count=0, escalations=0) == 1.0

    # Passed with escalations
    suboptimal = compute_outcome_reward(passed=True, error_count=0, escalations=2)
    assert 0.0 < suboptimal < 1.0

    # Failed
    assert compute_outcome_reward(passed=False) == -1.0


def test_laya_reward_tracker_flow():
    with tempfile.NamedTemporaryFile(suffix=".jsonl") as f:
        tracker = LayaOutcomeRewardTracker(log_path=f.name)
        tracker.register_decision(
            task_id="task_123",
            decision_id="dec_456",
            category="context_source",
            suggestion="indexed",
            options=["indexed", "rag"],
        )

        pairs = tracker.record_receipt_outcome(
            task_id="task_123",
            passed=True,
            error_count=0,
            escalations=0,
        )

        assert len(pairs) == 1
        assert pairs[0].reward == 1.0
        assert pairs[0].suggestion == "indexed"
