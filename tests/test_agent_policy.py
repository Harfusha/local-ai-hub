from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

import local_ai_hub.agent_policy as agent_policy
from local_ai_hub.agent_identity import AgentScope, ScopeContext
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_policy import (
    ActionRequest,
    Budget,
    BudgetCost,
    BudgetUnavailableError,
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


def test_external_call_reservation_is_durable_and_idempotent(tmp_path):
    store = AgentStateStore(tmp_path / "policy.sqlite", enabled=True)
    first_engine = PolicyEngine(store)
    second_engine = PolicyEngine(store)
    first_engine.set_budget("task-1", max_external_calls=1)

    reserved = first_engine.reserve_external_call("task-1", "a" * 32)
    duplicate = second_engine.reserve_external_call("task-1", "a" * 32)
    exhausted = second_engine.reserve_external_call("task-1", "b" * 32)

    assert reserved.reserved is True
    assert reserved.duplicate is False
    assert reserved.budget.used_external_calls == 1
    assert duplicate.reserved is False
    assert duplicate.duplicate is True
    assert duplicate.budget.used_external_calls == 1
    assert exhausted.exhausted is True
    assert exhausted.budget.used_external_calls == 1
    assert second_engine.get_budget("task-1").used_external_calls == 1


def test_external_call_reservation_rejects_cross_task_replay_and_bad_ids(tmp_path):
    engine = PolicyEngine(AgentStateStore(tmp_path / "policy.sqlite", enabled=True))
    engine.reserve_external_call("task-1", "c" * 32)

    with pytest.raises(ValueError, match="another task"):
        engine.reserve_external_call("task-2", "c" * 32)
    with pytest.raises(ValueError, match="32-character lowercase hex"):
        engine.reserve_external_call("task-1", "not-an-invocation-id")
    assert engine.get_budget("task-2").used_external_calls == 0


def test_external_call_reservation_requires_durable_budget_store():
    with pytest.raises(BudgetUnavailableError, match="durable external-call budget"):
        PolicyEngine().reserve_external_call("task-1", "d" * 32)


def test_external_call_reservation_serializes_concurrent_budget_admission(tmp_path):
    store = AgentStateStore(tmp_path / "policy.sqlite", enabled=True)
    engines = [PolicyEngine(store), PolicyEngine(store)]
    engines[0].set_budget("task-1", max_external_calls=1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda pair: pair[0].reserve_external_call("task-1", pair[1]),
            [(engines[0], "e" * 32), (engines[1], "f" * 32)],
        ))

    assert sum(result.reserved for result in results) == 1
    assert sum(result.exhausted for result in results) == 1
    assert engines[0].get_budget("task-1").used_external_calls == 1


def test_budget_consumption(engine: PolicyEngine):
    budget = engine.get_budget("task-1")
    assert budget.used_tokens == 0
    engine.consume("task-1", BudgetCost(tokens=500, compute_seconds=1.5, external_calls=2))
    updated = engine.get_budget("task-1")
    assert updated.used_tokens == 500
    assert updated.used_compute_seconds == 1.5
    assert updated.used_external_calls == 2


def test_persisted_budget_mutation_uses_bounded_write_transaction(monkeypatch, tmp_path):
    store = type(
        "StateStore",
        (),
        {"enabled": True, "db_path": str(tmp_path / "state.sqlite3")},
    )()
    engine = PolicyEngine(store)
    observed: list[dict[str, object]] = []
    write_transaction = agent_policy.write_transaction

    def record_transaction(con, **kwargs):
        observed.append(kwargs)
        return write_transaction(con, **kwargs)

    monkeypatch.setattr(agent_policy, "write_transaction", record_transaction)

    updated = engine.consume("task-bounded", BudgetCost(tokens=7))

    assert updated.used_tokens == 7
    assert any(call.get("max_duration_seconds") == 2.0 for call in observed)


def test_external_call_reservation_uses_bounded_write_transaction(monkeypatch, tmp_path):
    store = type(
        "StateStore",
        (),
        {"enabled": True, "db_path": str(tmp_path / "state.sqlite3")},
    )()
    engine = PolicyEngine(store)
    observed: list[dict[str, object]] = []
    write_transaction = agent_policy.write_transaction

    def record_transaction(con, **kwargs):
        observed.append(kwargs)
        return write_transaction(con, **kwargs)

    monkeypatch.setattr(agent_policy, "write_transaction", record_transaction)

    result = engine.reserve_external_call("task-bounded", "0123456789abcdef0123456789abcdef")

    assert result.reserved is True
    assert result.budget is not None
    assert result.budget.used_external_calls == 1
    assert any(call.get("max_duration_seconds") == 2.0 for call in observed)


def test_budget_exhaustion_diagnostic_includes_external_call_channel(engine):
    task = active_task()
    engine.set_budget(task.task_id, max_external_calls=1)
    engine.consume(task.task_id, BudgetCost(external_calls=1))
    decision = engine.authorize(ActionRequest(action="read"), task)
    assert decision.allowed is False
    assert "external_calls=1/1" in decision.reason


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
    with pytest.raises(agent_policy.BudgetUnavailableError, match="budget state unavailable"):
        PolicyEngine(store)

    assert "budget state initialization failed (OperationalError)" in caplog.text
    assert "database is locked" not in caplog.text
    assert str(tmp_path) not in caplog.text


def test_budget_storage_read_sqlite_error_is_logged_and_fails_closed(
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
    with pytest.raises(agent_policy.BudgetUnavailableError, match="budget state unavailable"):
        engine.get_budget("task-read")
    assert "task-read" not in engine._budgets
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
    with pytest.raises(agent_policy.BudgetUnavailableError, match="budget state unavailable"):
        engine._persist_budget(Budget(task_id="task-write"))

    assert "budget state persistence failed (OperationalError)" in caplog.text
    assert "database is locked" not in caplog.text
    assert str(tmp_path) not in caplog.text
