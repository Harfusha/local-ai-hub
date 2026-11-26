"""Hierarchical Speculative Cascade (0.5B -> 1.5B -> 3B/7B).

Multi-tier speculative decoding engine:
Tier 1 (0.5B): High-speed draft generation of candidate token sequence.
Tier 2 (1.5B): Fast syntax and semantic filtering / refinement of draft tokens.
Tier 3 (3B/7B): Parallel batch verification of refined tokens in a single target forward pass.

Supports sequential draft refinement and native engine-level speculative decoding.
Separates estimated heuristic speedup from authentic measured speedup.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Sequence


@dataclass(frozen=True)
class CascadeStepResult:
    draft_tokens: tuple[int, ...]
    refined_tokens: tuple[int, ...]
    accepted_tokens: tuple[int, ...]
    bonus_token: int | None
    total_tokens_emitted: int
    acceptance_rate: float
    estimated_speedup: float
    effective_speedup: float
    measured_speedup: float | None = None
    measured_latency_ms: float | None = None
    execution_mode: str = "sequential_draft_refinement"
    fallback_reason: str | None = None


def _validate_tokens(tokens: Any) -> list[int]:
    """Ensure token sequences consist of valid non-negative integers."""
    if not isinstance(tokens, (list, tuple)):
        return []
    valid: list[int] = []
    for tok in tokens:
        if isinstance(tok, int) and tok >= 0:
            valid.append(tok)
        else:
            break
    return valid


class HierarchicalSpeculativeCascade:
    """Orchestrates 3-tier speculative decoding cascade with callback validation."""

    def __init__(self, default_window_k: int = 4, max_window_k: int = 16) -> None:
        self.default_window_k = max(1, int(default_window_k))
        self.max_window_k = max(self.default_window_k, int(max_window_k))

    def run_step(
        self,
        prefix_tokens: Sequence[int],
        draft_model_fn: Callable[[Sequence[int], int], list[int]],
        refiner_model_fn: Callable[[Sequence[int], Sequence[int]], list[int]],
        target_model_fn: Callable[[Sequence[int], Sequence[int]], tuple[list[int], int | None]],
        window_k: int | None = None,
        *,
        measured_baseline_latency_ms: float | None = None,
        native_speculative: bool = False,
    ) -> CascadeStepResult:
        """Execute one cascade step: draft -> refine -> verify.

        Strictly enforces that accepted tokens are a valid prefix of refined tokens.
        """
        start_time = time.perf_counter()
        k = max(1, min(int(window_k if window_k is not None else self.default_window_k), self.max_window_k))
        clean_prefix = _validate_tokens(prefix_tokens)
        execution_mode = "native_speculative_decoding" if native_speculative else "sequential_draft_refinement"

        # 1. Tier 1: Draft model generates up to K candidate tokens
        try:
            raw_draft = draft_model_fn(clean_prefix, k)
            draft_tokens = _validate_tokens(raw_draft)[:k]
        except Exception:
            draft_tokens = []

        if not draft_tokens:
            # Fallback to single target model forward pass
            try:
                raw_accepted, raw_bonus = target_model_fn(clean_prefix, [])
                bonus = raw_bonus if (isinstance(raw_bonus, int) and raw_bonus >= 0) else None
            except Exception:
                bonus = None
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            measured_speedup = (
                round(measured_baseline_latency_ms / max(0.001, elapsed_ms), 3)
                if measured_baseline_latency_ms is not None else None
            )
            return CascadeStepResult(
                draft_tokens=(),
                refined_tokens=(),
                accepted_tokens=(),
                bonus_token=bonus,
                total_tokens_emitted=1 if bonus is not None else 0,
                acceptance_rate=0.0,
                estimated_speedup=1.0,
                effective_speedup=1.0,
                measured_speedup=measured_speedup,
                measured_latency_ms=round(elapsed_ms, 3),
                execution_mode=execution_mode,
                fallback_reason="draft_empty_or_failed",
            )

        # 2. Tier 2: Refiner model filters / refines draft tokens
        try:
            raw_refined = refiner_model_fn(clean_prefix, draft_tokens)
            refined_tokens = _validate_tokens(raw_refined)
        except Exception:
            refined_tokens = draft_tokens

        if not refined_tokens:
            refined_tokens = draft_tokens

        # 3. Tier 3: Target model verifies refined tokens
        try:
            raw_accepted, raw_bonus = target_model_fn(clean_prefix, refined_tokens)
            cand_accepted = _validate_tokens(raw_accepted)
            bonus_token = raw_bonus if (isinstance(raw_bonus, int) and raw_bonus >= 0) else None
        except Exception:
            cand_accepted = []
            bonus_token = None

        # Enforce strict prefix invariant: accepted tokens must strictly match refined tokens
        valid_len = 0
        for acc_tok, ref_tok in zip(cand_accepted, refined_tokens):
            if acc_tok == ref_tok:
                valid_len += 1
            else:
                break
        accepted_tokens = cand_accepted[:valid_len]

        n_accepted = len(accepted_tokens)
        total_emitted = n_accepted + (1 if bonus_token is not None else 0)
        acceptance_rate = n_accepted / max(1, len(refined_tokens))

        # Effective speedup model: target cost for N tokens is N forward passes.
        # Cascade cost: 1 parallel target pass + fast draft overhead (~0.15 target pass)
        effective_cost = 1.0 + 0.15
        speedup = total_emitted / effective_cost if total_emitted > 0 else 1.0

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        measured_speedup = (
            round(measured_baseline_latency_ms / max(0.001, elapsed_ms), 3)
            if measured_baseline_latency_ms is not None else None
        )

        return CascadeStepResult(
            draft_tokens=tuple(draft_tokens),
            refined_tokens=tuple(refined_tokens),
            accepted_tokens=tuple(accepted_tokens),
            bonus_token=bonus_token,
            total_tokens_emitted=total_emitted,
            acceptance_rate=round(acceptance_rate, 4),
            estimated_speedup=round(speedup, 2),
            effective_speedup=round(speedup, 2),
            measured_speedup=measured_speedup,
            measured_latency_ms=round(elapsed_ms, 3),
            execution_mode=execution_mode,
            fallback_reason=None,
        )
