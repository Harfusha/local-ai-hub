import pytest
from src.local_ai_hub.laya_budget_allocator import LayaBudgetAllocator


def test_budget_allocation_standard():
    allocator = LayaBudgetAllocator(default_budget=8192)

    plan = allocator.allocate(
        requested_budget=8192,
        task_complexity="standard",
        incoming_context_tokens=3000,
    )

    assert plan.total_budget == 8192
    assert plan.completion_reserve_tokens >= 2048
    assert plan.retrieval_tokens == 3000
    assert plan.trigger_skeletonize is False
    assert plan.trigger_context_prune is False
    assert plan.utilization_percent <= 100.0


def test_budget_allocation_overflow_triggers_skeletonize():
    allocator = LayaBudgetAllocator(default_budget=4096)

    # 4000 incoming context tokens in a 4096 budget: definitely exceeds retrieval capacity
    plan = allocator.allocate(
        requested_budget=4096,
        task_complexity="heavy",
        incoming_context_tokens=4000,
    )

    assert plan.trigger_skeletonize is True
    assert plan.trigger_context_prune is True
    assert plan.completion_reserve_tokens > 1000
