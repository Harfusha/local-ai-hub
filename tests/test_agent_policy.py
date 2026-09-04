from __future__ import annotations

import pytest

from local_ai_hub.agent_identity import AgentScope, ScopeContext
from local_ai_hub.agent_policy import (
    ActionRequest,
    Budget,
    BudgetCost,
    CapabilityGrant,
    PolicyDecision,
    PolicyEngine,
    RiskClass,
)
from local_ai_hub.agent_tasks import GoalContract, TaskState, TaskStatus


@pytest.fixture
def engine() -> PolicyEngine:
    return PolicyEngine()


def active_task() -> TaskState:
    return TaskState(
        task_id="task-123",
        status=TaskStatus.ACTIVE,
        contract=GoalContract(goal="test"),
        context=ScopeContext(task_id="task-123"),
    )


def write_action(path: str) -> ActionRequest:
    return ActionRequest(
        action="write",
        target=path,
        risk_class=RiskClass.WRITE,
    )


def test_delegate_cannot_expand_parent_capabilities(engine: PolicyEngine):
    parent = CapabilityGrant(
        grant_id="parent-g",
        allowed=frozenset({"read"}),
    )
    child = engine.delegate(parent, requested={"network"})
    assert child.allowed == frozenset()


def test_delegate_can_subset_parent_capabilities(engine: PolicyEngine):
    parent = CapabilityGrant(
        grant_id="parent-g",
        allowed=frozenset({"read", "write"}),
    )
    child = engine.delegate(parent, requested={"read"})
    assert child.allowed == frozenset({"read"})


def test_write_request_requires_precise_grant(engine: PolicyEngine):
    decision = engine.authorize(write_action("src/app.py"), active_task())
    assert decision.requires_approval is True
    assert decision.allowed is False


def test_write_request_succeeds_with_grant(engine: PolicyEngine):
    grant = CapabilityGrant(
        grant_id="g1",
        allowed=frozenset({"write"}),
    )
    decision = engine.authorize(write_action("src/app.py"), active_task(), grant=grant)
    assert decision.allowed is True
    assert decision.requires_approval is False


def test_budget_consumption(engine: PolicyEngine):
    budget = engine.get_budget("task-1")
    assert budget.used_tokens == 0
    engine.consume("task-1", BudgetCost(tokens=500, compute_seconds=1.5, external_calls=2))
    updated = engine.get_budget("task-1")
    assert updated.used_tokens == 500
    assert updated.used_compute_seconds == 1.5
    assert updated.used_external_calls == 2
