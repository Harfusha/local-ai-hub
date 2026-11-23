"""Adaptive KV-Cache Quantization & Token Pruner.

Implements token pruning and dynamic quantization for Key-Value caches:
1. Attention-guided token eviction (Heavy Hitter Oracle / StreamingLLM sink tokens + local window).
2. Dynamic Int4 and FP8 block quantization with min-max scaling.
3. 2-4x reduction in KV cache memory footprint with bounded reconstruction loss.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class KVCachePrunePlan:
    total_tokens: int
    retained_tokens: int
    evicted_tokens: int
    retained_indices: tuple[int, ...]
    evicted_indices: tuple[int, ...]
    sink_token_count: int
    heavy_hitter_count: int
    compression_ratio: float


@dataclass(frozen=True)
class QuantizedKVBlock:
    mode: str  # 'int4' or 'fp8'
    original_size_bytes: int
    quantized_size_bytes: int
    scale: float
    zero_point: int
    quantized_data: tuple[int, ...]
    memory_savings_percent: float


class AdaptiveKVCachePruner:
    """Manages attention-guided token pruning and block quantization for KV cache."""

    def __init__(self, default_sink_tokens: int = 4, default_local_window: int = 16) -> None:
        self.default_sink_tokens = default_sink_tokens
        self.default_local_window = default_local_window

    def plan_eviction(
        self,
        attention_scores: Sequence[float],
        target_budget: int,
        sink_tokens: int | None = None,
        local_window: int | None = None,
    ) -> KVCachePrunePlan:
        """Calculate retained and evicted token indices using sink + heavy-hitters + local window."""
        n = len(attention_scores)
        if target_budget >= n or n == 0:
            return KVCachePrunePlan(
                total_tokens=n,
                retained_tokens=n,
                evicted_tokens=0,
                retained_indices=tuple(range(n)),
                evicted_indices=(),
                sink_token_count=min(sink_tokens or self.default_sink_tokens, n),
                heavy_hitter_count=0,
                compression_ratio=1.0,
            )

        sinks = min(sink_tokens if sink_tokens is not None else self.default_sink_tokens, n)
        local_w = min(local_window if local_window is not None else self.default_local_window, n - sinks)

        # 1. Essential sink indices at beginning
        sink_indices = set(range(sinks))

        # 2. Essential local window indices at the end
        local_indices = set(range(max(sinks, n - local_w), n))

        protected = sink_indices | local_indices
        available_slots = max(0, target_budget - len(protected))

        # 3. Middle candidate tokens for Heavy Hitter selection
        candidates = [i for i in range(n) if i not in protected]
        # Sort candidates descending by attention score
        candidates.sort(key=lambda idx: attention_scores[idx], reverse=True)

        heavy_hitters = set(candidates[:available_slots])
        retained = sorted(list(protected | heavy_hitters))
        retained_set = set(retained)
        evicted = [i for i in range(n) if i not in retained_set]

        compression = n / max(1, len(retained))

        return KVCachePrunePlan(
            total_tokens=n,
            retained_tokens=len(retained),
            evicted_tokens=len(evicted),
            retained_indices=tuple(retained),
            evicted_indices=tuple(evicted),
            sink_token_count=len(sink_indices),
            heavy_hitter_count=len(heavy_hitters),
            compression_ratio=compression,
        )

    def quantize_block(
        self,
        values: Sequence[float],
        mode: str = "int4",
    ) -> QuantizedKVBlock:
        """Quantize floating point KV tensor slice to Int4 ([-8, 7]) or FP8 simulation ([-128, 127])."""
        if not values:
            return QuantizedKVBlock(
                mode=mode,
                original_size_bytes=0,
                quantized_size_bytes=0,
                scale=1.0,
                zero_point=0,
                quantized_data=(),
                memory_savings_percent=0.0,
            )

        orig_bytes = len(values) * 2  # Assuming FP16 baseline (2 bytes/val)
        min_val = min(values)
        max_val = max(values)

        if mode == "int4":
            # 4-bit signed integer range: -8 to 7 (15 steps)
            q_min, q_max = -8, 7
            quant_bytes = math.ceil(len(values) * 0.5)  # 4 bits = 0.5 byte
        elif mode == "fp8":
            # 8-bit range: -128 to 127
            q_min, q_max = -128, 127
            quant_bytes = len(values)  # 1 byte
        else:
            raise ValueError(f"Unsupported quantization mode: {mode}")

        val_range = max_val - min_val
        if val_range < 1e-8:
            scale = 1.0
            zero_point = 0
            quantized = tuple(0 for _ in values)
        else:
            scale = val_range / (q_max - q_min)
            zero_point = round(-min_val / scale) + q_min
            zero_point = max(q_min, min(q_max, zero_point))

            quantized_list: list[int] = []
            for v in values:
                q = round(v / scale) + zero_point
                q_clamped = max(q_min, min(q_max, q))
                quantized_list.append(q_clamped)
            quantized = tuple(quantized_list)

        savings = (1.0 - (quant_bytes / orig_bytes)) * 100.0

        return QuantizedKVBlock(
            mode=mode,
            original_size_bytes=orig_bytes,
            quantized_size_bytes=quant_bytes,
            scale=scale,
            zero_point=zero_point,
            quantized_data=quantized,
            memory_savings_percent=round(savings, 2),
        )

    def dequantize_block(self, block: QuantizedKVBlock) -> list[float]:
        """Dequantize quantized block back to floating point representation."""
        if not block.quantized_data:
            return []
        scale = block.scale
        zp = block.zero_point
        return [(q - zp) * scale for q in block.quantized_data]
