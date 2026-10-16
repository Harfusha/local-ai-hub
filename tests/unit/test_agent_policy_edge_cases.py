from __future__ import annotations

import math
import time
from pathlib import Path
import pytest

from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_policy import (
    ActionRequest,
    Budget,
    BudgetCost,
    CapabilityDescriptor,
    CapabilityGrant,
    PolicyDecision,
    PolicyEngine,
    RiskClass,
)
from local_ai_hub.agent_tasks import GoalContract, TaskState, TaskStatus


@pytest.fixture
def engine() -> PolicyEngine:
    return PolicyEngine()


def active_task(task_id: str = "task-test") -> TaskState:
    return TaskState(
        task_id=task_id,
        status=TaskStatus.ACTIVE,
        contract=GoalContract(goal="test"),
        context=ScopeContext(task_id=task_id),
    )


def test_capability_descriptor_and_grant_validation_and_helpers() -> None:
    desc = CapabilityDescriptor(
        name=" run_tool\x00 ",
        risk_class=RiskClass.WRITE,
        description=" desc\x00 ",
        requires_approval=True,
    )
    assert desc.name == "run_tool"
    assert desc.description == "desc"
    assert desc.requires_approval is True

    with pytest.raises(ValueError):
        CapabilityGrant(
            grant_id=" grant-1\x00 ", task_id="task-1",
            allowed=frozenset({"write"}), expires_at=100.0,
        )
    with pytest.raises(ValueError):
        CapabilityGrant(
            grant_id="grant-1", task_id=" task-1 ",
            allowed=frozenset({"write"}), expires_at=100.0,
        )
    with pytest.raises(ValueError, match="max_delegation_depth"):
        CapabilityGrant(
            grant_id="grant-1", task_id="task-1",
            allowed=frozenset({"write"}), expires_at=100.0,
            max_delegation_depth=-2,
        )

    grant = CapabilityGrant(
        grant_id="grant-1", task_id="task-1",
        allowed=frozenset({"write"}), denied=frozenset({"delete"}),
        expires_at=100.0, max_delegation_depth=0,
    )
    assert grant.grant_id == "grant-1"
    assert grant.task_id == "task-1"
    assert grant.allowed == frozenset({"write"})
    assert grant.denied == frozenset({"delete"})
    assert grant.expires_at == 100.0
    assert grant.can_delegate() is False
    assert grant.allows("write") is True
    assert grant.allows("delete") is False
    assert grant.denies("delete") is True
    assert grant.denies("read") is False
    assert grant.is_expired(now=150.0) is True
    assert grant.is_expired(now=50.0) is False

    # from_dict validation
    with pytest.raises(ValueError):
        CapabilityGrant.from_dict("invalid")  # type: ignore


def test_unknown_risk_classes_are_rejected() -> None:
    with pytest.raises(ValueError, match="risk_class"):
        CapabilityDescriptor(name="read_file", risk_class="unknown")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="risk_class"):
        ActionRequest(action="read_file", risk_class="unknown")  # type: ignore[arg-type]


def test_expired_grant_rejected_in_authorize(engine: PolicyEngine) -> None:
    task = active_task("task-exp")
    action = ActionRequest(action="write", target="test.py", risk_class=RiskClass.WRITE)
    expired_grant = CapabilityGrant(
        grant_id="g-exp",
        allowed=frozenset({"write"}),
        expires_at=time.time() - 10.0,
    )
    decision = engine.authorize(action, task, grant=expired_grant)
    assert decision.allowed is False
    assert "expired" in decision.reason


def test_zero_depth_grant_cannot_delegate_allowed_capabilities(engine: PolicyEngine) -> None:
    parent = CapabilityGrant(
        grant_id="parent-0",
        allowed=frozenset({"read", "write"}),
        max_delegation_depth=0,
    )
    child = engine.delegate(parent, requested={"read"})
    assert child.allowed == frozenset()
    assert child.max_delegation_depth == 0


def test_budget_and_cost_validation_and_helpers() -> None:
    cost = BudgetCost(tokens=-10, compute_seconds=-5.0, external_calls=-2)
    assert cost.tokens == 0
    assert cost.compute_seconds == 0.0
    assert cost.external_calls == 0
    assert cost.is_zero() is True

    cost_real = BudgetCost(tokens=100, compute_seconds=1.0, external_calls=1)
    assert cost_real.is_zero() is False

    budget = Budget(
        task_id=" b-1\x00 ",
        max_tokens=1000,
        used_tokens=250,
        max_compute_seconds=100.0,
        used_compute_seconds=20.0,
        max_external_calls=10,
        used_external_calls=2,
    )
    assert budget.task_id == "b-1"
    assert budget.remaining_tokens() == 750
    assert budget.remaining_compute_seconds() == 80.0
    assert budget.remaining_external_calls() == 8
    assert budget.token_utilization() == 0.25
    assert budget.is_exhausted() is False


def test_action_request_and_policy_decision_validation_and_helpers() -> None:
    req = ActionRequest(
        action=" read_file\x00 ",
        target=" /path/to/file\x00 ",
        risk_class=RiskClass.READ,
    )
    assert req.action == "read_file"
    assert req.target == "/path/to/file"
    assert req.is_read() is True
    assert req.is_write() is False
    assert req.is_network() is False

    dec = PolicyDecision(
        allowed=True,
        requires_approval=False,
        reason=" ok\x00 ",
        receipt_id=" r-1\x00 ",
    )
    assert dec.reason == "ok"
    assert dec.receipt_id == "r-1"
    assert dec.is_allowed() is True
    assert dec.is_denied() is False
    assert dec.needs_approval() is False


def test_policy_engine_budget_management(engine: PolicyEngine) -> None:
    task_id = "task-budget-mgmt"
    assert engine.has_budget(task_id) is False

    b = engine.set_budget(task_id, max_tokens=5000)
    assert engine.has_budget(task_id) is True
    assert b.max_tokens == 5000

    engine.consume(task_id, BudgetCost(tokens=500))
    b2 = engine.get_budget(task_id)
    assert b2.used_tokens == 500

    engine.reset_budget(task_id)
    b3 = engine.get_budget(task_id)
    assert b3.used_tokens == 0
    assert b3.max_tokens == 5000

    deleted = engine.delete_budget(task_id)
    assert deleted is True
    assert engine.has_budget(task_id) is False
