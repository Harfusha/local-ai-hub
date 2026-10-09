from __future__ import annotations

import sqlite3

import pytest

import local_ai_hub.agent_policy as agent_policy
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


@pytest.mark.parametrize("action", ["model", "model_inference"])
def test_local_model_inference_requires_explicit_grant(engine: PolicyEngine, action: str):
    request = ActionRequest(action=action, target="local-model")

    decision = engine.authorize(request, active_task())

    assert decision.allowed is False
    assert decision.requires_approval is True
    assert decision.side_effect_class == "model_execution"

    grant = CapabilityGrant(grant_id="local-model-on-demand", allowed=frozenset({action}))
    granted = engine.authorize(request, active_task(), grant=grant)
    assert granted.allowed is True
    assert granted.requires_approval is False


def test_budget_consumption(engine: PolicyEngine):
    budget = engine.get_budget("task-1")
    assert budget.used_tokens == 0
    engine.consume("task-1", BudgetCost(tokens=500, compute_seconds=1.5, external_calls=2))
    updated = engine.get_budget("task-1")
    assert updated.used_tokens == 500
    assert updated.used_compute_seconds == 1.5
    assert updated.used_external_calls == 2


def test_budget_storage_initialization_sqlite_error_is_logged_without_path(
    monkeypatch, tmp_path, caplog
):
    store = type(
        "StateStore",
        (),
        {"enabled": True, "db_path": str(tmp_path / "state.sqlite3")},
    )()

    def fail_retry(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(agent_policy, "retry_busy", fail_retry)
    PolicyEngine(store)

    assert "budget state initialization failed (OperationalError)" in caplog.text
    assert "database is locked" not in caplog.text
    assert str(tmp_path) not in caplog.text


def test_budget_storage_read_sqlite_error_is_logged_and_uses_memory_fallback(
    monkeypatch, tmp_path, caplog
):
    store = type(
        "StateStore",
        (),
        {"enabled": True, "db_path": str(tmp_path / "state.sqlite3")},
    )()
    engine = PolicyEngine(store)

    def fail_connect(_path):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(agent_policy, "connect_sqlite", fail_connect)
    budget = engine.get_budget("task-read")

    assert budget.used_tokens == 0
    assert "budget state read failed (OperationalError)" in caplog.text
    assert "database is locked" not in caplog.text
    assert str(tmp_path) not in caplog.text


def test_budget_storage_write_sqlite_error_is_logged(monkeypatch, tmp_path, caplog):
    store = type(
        "StateStore",
        (),
        {"enabled": True, "db_path": str(tmp_path / "state.sqlite3")},
    )()
    engine = PolicyEngine(store)

    def fail_connect(_path):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(agent_policy, "connect_sqlite", fail_connect)
    engine._persist_budget(Budget(task_id="task-write"))

    assert "budget state persistence failed (OperationalError)" in caplog.text
    assert "database is locked" not in caplog.text
    assert str(tmp_path) not in caplog.text
