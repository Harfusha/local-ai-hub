import pytest
from local_ai_hub.agent_policy import BudgetCost, Budget


def test_budget_cost_hardening():
    # Booleans and float('inf') should not crash or produce 1
    cost = BudgetCost(
        tokens=float("inf"),
        compute_seconds=True,
        external_calls=float("inf"),
    )
    assert cost.tokens == 0
    assert cost.compute_seconds == 0.0
    assert cost.external_calls == 0


def test_budget_hardening():
    # Booleans and float('inf') should safely fall back to defaults
    budget = Budget(
        task_id="task_1",
        max_tokens=float("inf"),
        used_tokens=True,
        max_compute_seconds=float("inf"),
        used_compute_seconds=True,
        max_external_calls=float("inf"),
        used_external_calls=True,
    )
    assert budget.max_tokens == 100_000
    assert budget.used_tokens == 0
    assert budget.max_compute_seconds == 600.0
    assert budget.used_compute_seconds == 0.0
    assert budget.max_external_calls == 50
    assert budget.used_external_calls == 0
