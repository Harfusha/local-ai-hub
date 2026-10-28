"""Contract tests for atomic, owner-bound increases of existing task budgets."""
import json
import sqlite3
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_policy import BudgetCost, PolicyEngine
from local_ai_hub.agent_tasks import CheckpointResponseBudgetError, GoalContract, TaskStore, TaskStatus


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


def test_watchdog_failed_task_can_raise_limits_without_resuming_or_resetting(budget_case):
    policy, state, _ = budget_case
    tasks = TaskStore(state)
    failed = tasks.fail("existing", actor="watchdog", reason="TASK_BUDGET_EXCEEDED")
    assert failed.status == TaskStatus.FAILED
    before = policy.get_budget("existing")
    with pytest.raises(PermissionError):
        increase(budget_case)
    result = increase(budget_case, actor="watchdog")
    assert tasks.get("existing") == failed
    assert policy.get_budget("existing").used_tokens == before.used_tokens
    assert policy.get_budget("existing").used_compute_seconds == before.used_compute_seconds
    assert policy.get_budget("existing").used_external_calls == before.used_external_calls
    assert result["budget"]["max_compute_seconds"] == 20
    event = state.events("budget:existing")
    assert event[-1].payload["task_owner"] == "watchdog"
    assert event[-1].event_id == result["audit_event_id"]


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


@pytest.mark.parametrize("identity", ["unrecognized", "", None, 1])
def test_unverified_authorization_identity_cannot_increase_budget(budget_case, identity):
    policy, _, _ = budget_case
    before = policy.get_budget("existing")
    with pytest.raises(PermissionError, match="authorization"):
        increase(budget_case, authorization_actor=identity)
    assert policy.get_budget("existing") == before


def budget_broker(case):
    from local_ai_hub.commands import CommandBroker
    policy, state, _ = case
    broker = CommandBroker.__new__(CommandBroker)
    broker.set_policy_engine(policy)
    broker.set_task_store(TaskStore(state))
    return broker


def test_broker_uses_persisted_task_owner_for_owner_admin_request(budget_case):
    policy, _, root = budget_case
    result = budget_broker(budget_case).increase_task_budget(
        "existing", root=str(root), reason="finish existing task",
        limits={"max_compute_seconds": 20}, authorization_actor="api_token",
        authorization_permissions=frozenset({"admin"}),
    )
    assert result["success"] is True
    assert policy.get_budget("existing").used_compute_seconds == 11


@pytest.mark.parametrize("actor,permissions", [
    ("api_token", frozenset({"read"})),
    ("supervisor", frozenset({"admin"})),
    ("action_token", frozenset({"read"})),
    ("unrecognized", frozenset({"write"})),
    ("api_token", ["admin"]),
])
def test_broker_rejects_missing_write_authority(budget_case, actor, permissions):
    policy, _, root = budget_case
    before = policy.get_budget("existing")
    with pytest.raises(PermissionError, match="authorization"):
        budget_broker(budget_case).increase_task_budget(
            "existing", root=str(root), reason="finish", limits={"max_compute_seconds": 20},
            authorization_actor=actor, authorization_permissions=permissions,
        )
    assert policy.get_budget("existing") == before


def test_response_budget_rejection_precedes_mutation_and_audit(budget_case):
    policy, state, _ = budget_case
    before = policy.get_budget("existing")
    with pytest.raises(CheckpointResponseBudgetError):
        increase(budget_case, response_budget_tokens=128)
    assert policy.get_budget("existing") == before
    with closing(sqlite3.connect(state.db_path)) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM agent_events WHERE kind='task.budget_increased'"
        ).fetchone()[0] == 0


def test_public_contract_has_explicit_scope_without_caller_identity():
    from local_ai_hub.operation_contracts import validate_operation_arguments
    args = {"root": "C:/existing", "task_id": "existing", "reason": "finish",
            "budget": {"max_compute_seconds": 20}}
    assert validate_operation_arguments("local_ai_coord", "task_budget_increase", args) is None
    assert validate_operation_arguments("local_ai_coord", "task_budget_increase",
                                        {**args, "owner": "pretend-owner"})
    assert validate_operation_arguments("local_ai_coord", "task_get",
                                        {"task_id": "existing", "budget": args["budget"]})


def test_sdk_budget_action_preserves_canonical_payload(monkeypatch):
    from local_ai_hub.client import HubClient
    client = HubClient.__new__(HubClient)
    calls = []
    monkeypatch.setattr(client, "post", lambda path, payload: calls.append((path, payload)) or {"success": True})
    result = client.coord("task_budget_increase", root="C:/existing", task_id="existing",
                          reason="finish", budget={"max_compute_seconds": 20})
    assert result["success"] is True
    assert calls == [("/api/agent-state/tasks", {
        "action": "budget_increase", "root": "C:/existing", "task_id": "existing",
        "reason": "finish", "budget": {"max_compute_seconds": 20},
    })]


@pytest.fixture
def http_budget_handler(budget_case, monkeypatch):
    from types import SimpleNamespace
    from local_ai_hub import http_server
    _, state, root = budget_case
    config = {"security": {"api_token": "owner-token-at-least-sixteen",
                           "supervisor_token": "supervisor-token-at-least-sixteen",
                           "api_token_permissions": ["admin"], "allowed_roots": [str(root)]}}
    audit = []
    app = SimpleNamespace(config=config, agent_tasks=TaskStore(state),
                          commands=budget_broker(budget_case),
                          telemetry=SimpleNamespace(record_system=lambda *a, **kw: audit.append((a, kw))))
    monkeypatch.setattr(http_server, "APP", app)
    # Coordination ID normally comes from the server project resolver. All token,
    # canonical root/allowlist, task-scope and persisted budget checks remain real.
    monkeypatch.setattr(http_server, "_trusted_project_context",
                        lambda _: SimpleNamespace(coordination_id="repository"))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/agent-state/tasks"
    handler.command = "POST"
    handler.client_address = ("127.0.0.1", 0)
    handler.headers = {"X-LocalAI-Token": config["security"]["api_token"],
                       "X-LocalAI-Agent": "forged-unrelated-agent"}
    replies = []
    handler._send = lambda status, payload: replies.append((status, payload))
    payload = {"action": "budget_increase", "root": str(root), "task_id": "existing",
               "reason": "Finish owner-approved work", "budget": {"max_compute_seconds": 20}}
    return handler, payload, replies, config, audit


def test_http_owner_admin_changes_budget_without_agent_header_authority(http_budget_handler, budget_case):
    handler, payload, replies, _, _ = http_budget_handler
    handler._task_budget_increase(payload)
    assert replies[-1][0] == 200
    assert replies[-1][1]["budget"]["used_compute_seconds"] == 11
    with closing(sqlite3.connect(budget_case[1].db_path)) as con:
        assert con.execute('SELECT actor FROM agent_events WHERE event_id=?',
                           (replies[-1][1]['audit_event_id'],)).fetchone()[0] == 'api_token'
    assert budget_case[0].get_budget("existing").max_compute_seconds == 20


@pytest.mark.parametrize("case", ["wrong_token", "no_write", "supervisor", "remote_without_token", "caller_owner", "no_root", "wrong_root"])
def test_http_rejects_untrusted_authority_and_scope(http_budget_handler, budget_case, case, tmp_path):
    handler, payload, replies, config, _ = http_budget_handler
    policy, _, _ = budget_case
    before = policy.get_budget("existing")
    if case == "wrong_token":
        handler.headers["X-LocalAI-Token"] = "wrong-token"
    elif case == "no_write":
        config["security"]["api_token_permissions"] = ["read"]
    elif case == "supervisor":
        handler.headers["X-LocalAI-Token"] = config["security"]["supervisor_token"]
    elif case == "remote_without_token":
        config["security"].update(api_token="", supervisor_token="")
        handler.headers.clear()
        handler.client_address = ("192.0.2.10", 0)
    elif case == "caller_owner":
        payload["owner"] = "owner"
    elif case == "no_root":
        payload.pop("root")
    else:
        other = tmp_path / "unauthorized"
        other.mkdir()
        payload["root"] = str(other)
    handler._task_budget_increase(payload)
    assert replies[-1][0] in (400, 403, 404)
    assert policy.get_budget("existing") == before


@pytest.mark.parametrize("case,expected_actor", [("write", "api_token"), ("local", "local")])
@pytest.mark.parametrize("failed", [False, True])
def test_budget_increase_uses_ordinary_write_access_and_real_audit_identity(
        http_budget_handler, budget_case, case, expected_actor, failed):
    handler, payload, replies, config, _ = http_budget_handler
    policy, state, _ = budget_case
    tasks = TaskStore(state)
    if failed:
        tasks.fail('existing', actor='watchdog', reason='TASK_BUDGET_EXCEEDED')
    original_task = tasks.get('existing')
    config["security"]["api_token_permissions"] = ["write"]
    if case == "local":
        config["security"].update(api_token="", supervisor_token="")
        handler.headers.clear()
    before = policy.get_budget("existing")
    handler._task_budget_increase(payload)
    assert replies[-1][0] == 200, replies
    result = replies[-1][1]
    after = policy.get_budget("existing")
    assert after.max_compute_seconds == 20
    assert tasks.get('existing').status == original_task.status
    assert tasks.get('existing').owner == original_task.owner
    assert (after.used_tokens, after.used_compute_seconds, after.used_external_calls) == (
        before.used_tokens, before.used_compute_seconds, before.used_external_calls)
    with closing(sqlite3.connect(state.db_path)) as con:
        actor, body = con.execute('SELECT actor,payload FROM agent_events WHERE event_id=?',
                                  (result['audit_event_id'],)).fetchone()
    assert actor == expected_actor
    assert json.loads(body)['task_owner'] == original_task.owner


@pytest.mark.parametrize("actor,permissions", [
    ("local", frozenset()), ("api_token", frozenset({"write"})),
    ("action_token", frozenset({"api:write"})),
])
def test_broker_accepts_ordinary_write_clients(budget_case, actor, permissions):
    _, _, root = budget_case
    result = budget_broker(budget_case).increase_task_budget(
        'existing', root=str(root), reason='Operator permits ordinary clients',
        limits={'max_compute_seconds': 20}, authorization_actor=actor,
        authorization_permissions=permissions)
    assert result['success'] is True
    assert result['budget']['used_compute_seconds'] == 11


def test_mcp_budget_roundtrip_retains_audit_and_counters(monkeypatch, tmp_path):
    from local_ai_hub import mcp_server
    from local_ai_hub.operational_mode import OperationalModeSnapshot
    monkeypatch.setattr(mcp_server, "CFG", {"debug_traces": {"enabled": False}})
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _: OperationalModeSnapshot("active", 0, None))
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **kwargs: None)
    calls = []
    expected = {"success": True, "task_id": "existing", "audit_event_id": "evt-real",
                "before": {"max_compute_seconds": 10, "used_compute_seconds": 11},
                "budget": {"max_compute_seconds": 20, "used_compute_seconds": 11}}
    # local_ai_coord uses the adapter's delegated HubClient.coord method, whose
    # request is made through the wrapped client's post method.
    def post(path, payload, **_kwargs):
        calls.append((path, payload))
        return expected

    monkeypatch.setattr(mcp_server.CLIENT._client, "post", post)
    result = mcp_server.local_ai_coord(action="task_budget_increase", root=str(tmp_path),
                                      task_id="existing", reason="finish",
                                      budget={"max_compute_seconds": 20}, max_response_tokens=3200)
    assert result["success"] is True
    for key in ("before", "budget", "audit_event_id"):
        assert result[key] == expected[key]
    assert calls[0][0] == "/api/agent-state/tasks"
    assert calls[0][1]["action"] == "budget_increase"
    assert calls[0][1]["budget"] == {"max_compute_seconds": 20}
    assert "owner" not in calls[0][1] and "authorization_actor" not in calls[0][1]
