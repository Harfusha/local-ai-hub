"""Contract tests for atomic, owner-bound increases of existing task budgets."""
import json
import sqlite3
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_policy import BudgetCost, PolicyEngine
from local_ai_hub.agent_tasks import GoalContract, TaskStore, TaskStatus


@pytest.fixture
def budget_case(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    state = AgentStateStore(tmp_path / "agent-state.sqlite", enabled=True)
    tasks = TaskStore(state)
    tasks.create(
        GoalContract(goal="Existing task", acceptance_criteria=("validated",)),
        ScopeContext(repository_id="repository", task_id="existing"),
        task_id="existing", actor="owner", repo_root=str(root),
    )
    policy = PolicyEngine(state)
    policy.set_budget("existing", max_tokens=100, max_compute_seconds=10, max_external_calls=5)
    policy.consume("existing", BudgetCost(tokens=90, compute_seconds=11, external_calls=4))
    return policy, state, root


def increase(case, **overrides):
    policy, _, root = case
    arguments = dict(actor="owner", authorization_actor="api_token", repo_root=str(root), reason="Finish existing validation",
                     limits={"max_compute_seconds": 20})
    arguments.update(overrides)
    return policy.increase_task_budget("existing", **arguments)


def test_increase_preserves_usage_and_omitted_limits_and_records_audit(budget_case):
    policy, state, _ = budget_case
    before = policy.get_budget("existing")
    result = increase(budget_case)
    after = policy.get_budget("existing")
    assert (after.used_tokens, after.used_compute_seconds, after.used_external_calls) == (90, 11, 4)
    assert (after.max_tokens, after.max_compute_seconds, after.max_external_calls) == (100, 20, 5)
    with closing(sqlite3.connect(state.db_path)) as con:
        row = con.execute(
            "SELECT actor,payload FROM agent_events WHERE event_id=?", (result["audit_event_id"],)
        ).fetchone()
    assert row[0] == "api_token"
    payload = json.loads(row[1])
    assert payload["task_owner"] == "owner"
    assert payload["reason"] == "Finish existing validation"
    assert payload["before"]["used_compute_seconds"] == before.used_compute_seconds
    assert payload["after"] == result["budget"]


@pytest.mark.parametrize("limits", [
    {}, {"max_tokens": 100}, {"max_tokens": 99}, {"max_tokens": True},
    {"max_tokens": "200"}, {"max_tokens": 200.0}, {"max_tokens": 2**63},
    {"max_compute_seconds": float("nan")}, {"max_compute_seconds": float("inf")},
    {"max_compute_seconds": True}, {"max_external_calls": -1},
    {"max_tokens": 200, "max_external_calls": 4}, {"used_tokens": 0},
])
def test_invalid_or_nonincreasing_request_preserves_entire_budget(budget_case, limits):
    policy, _, _ = budget_case
    before = policy.get_budget("existing")
    with pytest.raises(ValueError):
        increase(budget_case, limits=limits)
    assert policy.get_budget("existing") == before


def test_owner_and_repository_cannot_be_substituted(budget_case, tmp_path):
    policy, _, _ = budget_case
    before = policy.get_budget("existing")
    other = tmp_path / "other"
    other.mkdir()
    for overrides in ({"actor": "other"}, {"repo_root": str(other)}):
        with pytest.raises(PermissionError):
            increase(budget_case, **overrides)
    assert policy.get_budget("existing") == before


def test_audit_failure_rolls_back_budget_and_cache(budget_case, monkeypatch):
    policy, state, _ = budget_case
    before = policy.get_budget("existing")

    def unavailable(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(state, "append_in_transaction", unavailable)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        increase(budget_case)
    assert policy.get_budget("existing") == before
    assert PolicyEngine(state).get_budget("existing") == before


def test_missing_task_does_not_create_budget(budget_case):
    policy, _, root = budget_case
    with pytest.raises(KeyError):
        policy.increase_task_budget("missing", actor="owner", repo_root=str(root),
                                    reason="existing only", limits={"max_tokens": 200},
                                    authorization_actor="api_token")
    assert not policy.has_budget("missing")


def test_empty_reason_does_not_change_budget(budget_case):
    with pytest.raises(ValueError, match="reason"):
        increase(budget_case, reason=" ")


def test_changed_owner_is_checked_from_persisted_task(budget_case):
    policy, state, _ = budget_case
    before = policy.get_budget("existing")
    TaskStore(state).transition("existing", TaskStatus.ACTIVE, actor="other", reason="new owner",
                                idempotency_key="owner-transfer")
    with pytest.raises(PermissionError):
        increase(budget_case)
    assert policy.get_budget("existing") == before


def test_concurrent_engines_cannot_apply_same_increase_twice(budget_case):
    _, state, root = budget_case

    def attempt(_):
        policy = PolicyEngine(state)
        try:
            return policy.increase_task_budget(
                "existing", actor="owner", repo_root=str(root), reason="finish",
                limits={"max_compute_seconds": 20}, authorization_actor="api_token",
            )["success"]
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sorted(results) == [False, True]
    after = PolicyEngine(state).get_budget("existing")
    assert (after.used_tokens, after.used_compute_seconds, after.used_external_calls) == (90, 11, 4)
    with closing(sqlite3.connect(state.db_path)) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM agent_events WHERE kind='task.budget_increased'"
        ).fetchone()[0] == 1


@pytest.mark.parametrize("identity", ["supervisor", "action_token", "local", "unrecognized", ""])
def test_other_authorization_kinds_cannot_increase_budget(budget_case, identity):
    policy, _, _ = budget_case
    before = policy.get_budget("existing")
    with pytest.raises(PermissionError, match="installation owner"):
        increase(budget_case, authorization_actor=identity)
    assert policy.get_budget("existing") == before
