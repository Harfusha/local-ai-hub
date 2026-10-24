"""Acceptance coverage for exhausted task-budget diagnostics at the broker gate."""

from __future__ import annotations

import pytest

from local_ai_hub.agent_policy import BudgetCost, PolicyEngine
from local_ai_hub.commands import CommandBroker
from local_ai_hub import mcp_server


@pytest.mark.parametrize(
    ("exhausted_channel", "cost", "expected_usage"),
    [
        ("tokens", BudgetCost(tokens=10), {"used_tokens": "10", "used_compute_seconds": "0.0", "used_external_calls": "0"}),
        ("compute", BudgetCost(compute_seconds=20), {"used_tokens": "0", "used_compute_seconds": "20.0", "used_external_calls": "0"}),
        ("external_calls", BudgetCost(external_calls=30), {"used_tokens": "0", "used_compute_seconds": "0.0", "used_external_calls": "30"}),
    ],
)
def test_broker_reports_each_budget_counter_before_any_command_execution(
    tmp_path, monkeypatch, exhausted_channel, cost, expected_usage
):
    task_id = f"budget-diagnostics-{exhausted_channel}"
    engine = PolicyEngine()
    engine.set_budget(
        task_id,
        max_tokens=10,
        max_compute_seconds=20,
        max_external_calls=30,
    )
    current = engine.consume(task_id, cost)
    assert current.is_exhausted(), exhausted_channel

    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {"enabled": True},
        },
        repo_state=object(),
    )
    broker.set_policy_engine(engine)

    def unexpected_execution(*args, **kwargs):
        pytest.fail("exhausted task reached process execution")

    monkeypatch.setattr("local_ai_hub.commands.subprocess.Popen", unexpected_execution)
    result = broker.run(
        "git status --short",
        str(tmp_path),
        task_id=task_id,
        record_verification=False,
        force=True,
        bypass_cache=True,
    )

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert result.get("budget_exhausted") is True, result
    diagnostic = result["error"]
    for field, value in {
        "max_tokens": "10",
        **expected_usage,
        "max_compute_seconds": "20.0",
        "max_external_calls": "30",
    }.items():
        assert f"{field}={value}" in diagnostic

    cause = {
        "tokens": "tokens=10/10",
        "compute": "compute_seconds=20.0/20.0",
        "external_calls": "external_calls=30/30",
    }[exhausted_channel]
    for profile in ("compact", "minimal"):
        token = mcp_server._CURRENT_RESPONSE_OPTIONS.set({
            "tool": "local_ai_coord",
            "action": "task_resume",
            "max_response_tokens": 128,
            "response_profile": profile,
        })
        try:
            projected = mcp_server._compact(result, task_kind="command")
        finally:
            mcp_server._CURRENT_RESPONSE_OPTIONS.reset(token)
        assert projected["success"] is False
        assert projected["terminal"] is True
        assert projected["retryable"] is False
        assert cause in projected["error"], projected
