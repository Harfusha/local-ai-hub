import pytest
from src.local_ai_hub.speculative_cascade import (
    HierarchicalSpeculativeCascade,
    CascadeStepResult,
)


def test_lah_010_measured_vs_estimated_speedup():
    cascade = HierarchicalSpeculativeCascade(default_window_k=4)
    prefix = [101]

    def draft_fn(pref, k):
        return [201, 202, 203, 204][:k]

    def refiner_fn(pref, draft):
        return list(draft)

    def target_fn(pref, refined):
        return list(refined), 300

    # Test with simulated baseline latency of 50.0 ms
    result = cascade.run_step(
        prefix,
        draft_fn,
        refiner_fn,
        target_fn,
        window_k=4,
        measured_baseline_latency_ms=50.0,
        native_speculative=True,
    )

    assert result.execution_mode == "native_speculative_decoding"
    assert result.estimated_speedup > 3.0
    assert result.measured_speedup is not None
    assert result.measured_speedup > 0.0
    assert result.measured_latency_ms is not None
    assert result.fallback_reason is None


def test_lah_011_strict_prefix_invariant_enforcement():
    cascade = HierarchicalSpeculativeCascade(default_window_k=4)
    prefix = [100]

    def draft_fn(pref, k):
        return [10, 20, 30, 40]

    def refiner_fn(pref, draft):
        return list(draft)

    # Adversarial target returns tokens that diverge at index 2: [10, 20, 999, 40]
    def adversarial_target_fn(pref, refined):
        return [10, 20, 999, 40], None

    result = cascade.run_step(prefix, draft_fn, refiner_fn, adversarial_target_fn, window_k=4)

    # Prefix invariant: must be truncated to exactly [10, 20], rejecting 999 and subsequent 40!
    assert result.accepted_tokens == (10, 20)
    assert result.acceptance_rate == 0.5


def test_lah_011_completely_divergent_target_tokens():
    cascade = HierarchicalSpeculativeCascade(default_window_k=4)
    prefix = [100]

    def draft_fn(pref, k):
        return [10, 20, 30, 40]

    def refiner_fn(pref, draft):
        return list(draft)

    # Target rejects first token immediately
    def rejecting_target_fn(pref, refined):
        return [999], 888

    result = cascade.run_step(prefix, draft_fn, refiner_fn, rejecting_target_fn, window_k=4)

    assert result.accepted_tokens == ()
    assert result.bonus_token == 888
    assert result.total_tokens_emitted == 1
    assert result.acceptance_rate == 0.0


def test_lah_011_callback_exception_and_boundary_resilience():
    cascade = HierarchicalSpeculativeCascade(default_window_k=4, max_window_k=8)
    prefix = [100]

    # 1. Draft callback raises exception
    def failing_draft_fn(pref, k):
        raise RuntimeError("Draft model OOM")

    def target_fn(pref, refined):
        assert len(refined) == 0
        return [], 555

    res_fail = cascade.run_step(prefix, failing_draft_fn, lambda p, d: list(d), target_fn)
    assert res_fail.draft_tokens == ()
    assert res_fail.bonus_token == 555
    assert res_fail.fallback_reason == "draft_empty_or_failed"

    # 2. Window K clamping: negative K or excessive K
    recorded_k = []
    def recording_draft_fn(pref, k):
        recorded_k.append(k)
        return [1, 2]

    cascade.run_step(prefix, recording_draft_fn, lambda p, d: list(d), lambda p, r: (list(r), None), window_k=-10)
    assert recorded_k[-1] == 1  # Clamped to min 1

    cascade.run_step(prefix, recording_draft_fn, lambda p, d: list(d), lambda p, r: (list(r), None), window_k=1000)
    assert recorded_k[-1] == 8  # Clamped to max_window_k=8
