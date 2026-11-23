import pytest
from src.local_ai_hub.speculative_cascade import HierarchicalSpeculativeCascade


def test_hierarchical_speculative_cascade_full_acceptance():
    cascade = HierarchicalSpeculativeCascade(default_window_k=4)

    prefix = [101, 102]

    # Tier 1 draft (0.5B): proposes [201, 202, 203, 204]
    def draft_fn(pref, k):
        return [201, 202, 203, 204][:k]

    # Tier 2 refiner (1.5B): accepts 201, 202, 203, but refines 204 -> 205
    def refiner_fn(pref, draft):
        res = list(draft)
        if len(res) >= 4 and res[3] == 204:
            res[3] = 205
        return res

    # Tier 3 target (3B): accepts all refined tokens [201, 202, 203, 205] and produces bonus token 300
    def target_fn(pref, refined):
        return list(refined), 300

    result = cascade.run_step(prefix, draft_fn, refiner_fn, target_fn, window_k=4)

    assert result.draft_tokens == (201, 202, 203, 204)
    assert result.refined_tokens == (201, 202, 203, 205)
    assert result.accepted_tokens == (201, 202, 203, 205)
    assert result.bonus_token == 300
    assert result.total_tokens_emitted == 5
    assert result.acceptance_rate == 1.0
    assert result.effective_speedup > 3.0


def test_hierarchical_speculative_cascade_partial_acceptance():
    cascade = HierarchicalSpeculativeCascade(default_window_k=4)

    prefix = [101]

    def draft_fn(pref, k):
        return [501, 502, 503, 504]

    def refiner_fn(pref, draft):
        return list(draft)

    # Target model accepts only first 2 tokens [501, 502] and produces divergence token 999
    def target_fn(pref, refined):
        return [501, 502], 999

    result = cascade.run_step(prefix, draft_fn, refiner_fn, target_fn, window_k=4)

    assert result.accepted_tokens == (501, 502)
    assert result.bonus_token == 999
    assert result.total_tokens_emitted == 3
    assert result.acceptance_rate == 0.5
    assert result.effective_speedup > 1.5
