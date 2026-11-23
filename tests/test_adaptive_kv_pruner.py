import pytest
from src.local_ai_hub.adaptive_kv_pruner import AdaptiveKVCachePruner


def test_kv_token_pruning():
    pruner = AdaptiveKVCachePruner(default_sink_tokens=2, default_local_window=3)

    # 10 tokens: 0..9
    # Sinks: 0, 1 (protected)
    # Local window: 7, 8, 9 (protected)
    # Candidates in middle: 2, 3, 4, 5, 6
    # Let attention scores make 4 have highest attention (0.9), others low (0.1)
    scores = [0.1, 0.1, 0.05, 0.05, 0.95, 0.02, 0.03, 0.1, 0.1, 0.1]

    # Target budget: 6 tokens (2 sinks + 3 local + 1 heavy hitter)
    plan = pruner.plan_eviction(scores, target_budget=6, sink_tokens=2, local_window=3)

    assert plan.total_tokens == 10
    assert plan.retained_tokens == 6
    assert plan.evicted_tokens == 4

    # Check sink tokens are retained
    assert 0 in plan.retained_indices
    assert 1 in plan.retained_indices

    # Check local window tokens are retained
    assert 7 in plan.retained_indices
    assert 8 in plan.retained_indices
    assert 9 in plan.retained_indices

    # Check that highest attention token (4) is retained
    assert 4 in plan.retained_indices

    # Low attention middle tokens must be evicted
    assert 2 in plan.evicted_indices
    assert 3 in plan.evicted_indices
    assert 5 in plan.evicted_indices
    assert 6 in plan.evicted_indices


def test_kv_block_quantization():
    pruner = AdaptiveKVCachePruner()

    original_floats = [0.12, -0.45, 1.34, 0.88, -1.2, 0.0, 0.55, -0.1]

    # Test INT4 quantization
    int4_block = pruner.quantize_block(original_floats, mode="int4")
    assert int4_block.mode == "int4"
    assert int4_block.memory_savings_percent == 75.0  # FP16 (16B) -> INT4 (4B)
    assert all(-8 <= q <= 7 for q in int4_block.quantized_data)

    dequant_int4 = pruner.dequantize_block(int4_block)
    assert len(dequant_int4) == len(original_floats)
    # Mean absolute error should be bounded
    mae_int4 = sum(abs(a - b) for a, b in zip(original_floats, dequant_int4)) / len(original_floats)
    assert mae_int4 < 0.25

    # Test FP8 simulation quantization
    fp8_block = pruner.quantize_block(original_floats, mode="fp8")
    assert fp8_block.mode == "fp8"
    assert fp8_block.memory_savings_percent == 50.0  # FP16 (16B) -> FP8 (8B)
    assert all(-128 <= q <= 127 for q in fp8_block.quantized_data)

    dequant_fp8 = pruner.dequantize_block(fp8_block)
    mae_fp8 = sum(abs(a - b) for a, b in zip(original_floats, dequant_fp8)) / len(original_floats)
    assert mae_fp8 < 0.05
