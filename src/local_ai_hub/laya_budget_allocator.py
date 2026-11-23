"""Laya Token-Budget Predictive Allocator.

Predictively partitions total context token budget (e.g. 8192, 16384, 32768) into:
- System & Superpowers rules
- Retrieval context (code & RAG)
- Agent OS memory & verification receipts
- Guaranteed completion reserve (prevents truncated code blocks / unexpected EOF)

Emits pruning recommendations (trigger_skeletonize, trigger_prune) when context exceeds budget.
"""

from __future__ import annotations

# import math
from dataclasses import dataclass


@dataclass(frozen=True)
class BudgetAllocationPlan:
    total_budget: int
    system_tokens: int
    memory_tokens: int
    retrieval_tokens: int
    completion_reserve_tokens: int
    trigger_skeletonize: bool
    trigger_context_prune: bool
    utilization_percent: float


class LayaBudgetAllocator:
    """Calculates optimal prompt partition and completion guarantees in <1ms."""

    def __init__(self, default_budget: int = 8192) -> None:
        self.default_budget = default_budget

    def allocate(
        self,
        requested_budget: int | None = None,
        task_complexity: str = "standard",  # "simple", "standard", "heavy"
        incoming_context_tokens: int = 0,
    ) -> BudgetAllocationPlan:
        """Compute optimal token distribution for LLM prompt and completion."""
        max_b = requested_budget or self.default_budget

        # 1. Completion reserve based on complexity
        if task_complexity == "simple":
            completion_reserve = min(1024, int(max_b * 0.20))
            system_tokens = min(600, int(max_b * 0.10))
            memory_tokens = min(300, int(max_b * 0.05))
        elif task_complexity == "heavy":
            completion_reserve = min(4096, int(max_b * 0.35))
            system_tokens = min(1500, int(max_b * 0.15))
            memory_tokens = min(800, int(max_b * 0.08))
        else:  # standard
            completion_reserve = min(2048, int(max_b * 0.25))
            system_tokens = min(1000, int(max_b * 0.12))
            memory_tokens = min(500, int(max_b * 0.06))

        # Remaining capacity available for code / documentation retrieval
        fixed_overhead = system_tokens + memory_tokens + completion_reserve
        available_retrieval = max(512, max_b - fixed_overhead)

        # Determine if compression/skeletonization triggers are needed
        trigger_skeletonize = incoming_context_tokens > available_retrieval
        trigger_prune = incoming_context_tokens > (available_retrieval * 1.5)

        retrieval_allocated = min(available_retrieval, incoming_context_tokens) if incoming_context_tokens > 0 else available_retrieval
        total_used = system_tokens + memory_tokens + retrieval_allocated + completion_reserve
        utilization = (total_used / max_b) * 100.0

        return BudgetAllocationPlan(
            total_budget=max_b,
            system_tokens=system_tokens,
            memory_tokens=memory_tokens,
            retrieval_tokens=retrieval_allocated,
            completion_reserve_tokens=completion_reserve,
            trigger_skeletonize=trigger_skeletonize,
            trigger_context_prune=trigger_prune,
            utilization_percent=round(utilization, 2),
        )
