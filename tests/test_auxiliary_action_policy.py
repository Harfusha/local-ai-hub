from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from local_ai_hub.agent_policy import (
    ActionRequest,
    CapabilityGrant,
    PolicyDecision,
    PolicyEngine,
    RiskClass,
)
from local_ai_hub.commands import CommandBroker
from local_ai_hub.services import LocalAIServices


@pytest.fixture
def policy() -> PolicyEngine:
    return PolicyEngine()


@pytest.mark.parametrize(
    ("action", "side_effect_class"),
    [
        ("run", "process_execution"),
        ("repair_loop", "workspace_write"),
        ("format", "workspace_write"),
        ("spawn_daemon", "process_lifecycle"),
        ("stop_daemon", "process_lifecycle"),
        ("http_probe", "network_access"),
        ("stash_save", "git_mutation"),
        ("diff_hunk_stage", "git_mutation"),
        ("record_mock", "test_fixture_write"),
        ("mock_server_start", "network_listener"),
        ("bundle", "artifact_write"),
        ("config", "system_configuration"),
        ("model", "model_execution"),
    ],
)
def test_auxiliary_actions_share_policy_metadata_and_require_grant(
    policy: PolicyEngine, action: str, side_effect_class: str
) -> None:
    decision = policy.authorize(
        ActionRequest(action=action, risk_class=RiskClass.READ), task=None
    )

    assert decision.allowed is False
    assert decision.owner == "agent_policy"
    assert decision.side_effect_class == side_effect_class


def test_developer_authorized_auxiliary_mutation_still_allowed(
    policy: PolicyEngine,
) -> None:
    grant = CapabilityGrant(
        grant_id="developer-approved",
        allowed=frozenset({"repair_loop"}),
    )

    decision = policy.authorize(
        ActionRequest(action="repair_loop", risk_class=RiskClass.READ),
        task=None,
        grant=grant,
    )

    assert decision.allowed is True
    assert decision.owner == "agent_policy"
    assert decision.side_effect_class == "workspace_write"


def test_unknown_auxiliary_action_fails_closed_even_when_marked_read(
    policy: PolicyEngine,
) -> None:
    decision = policy.authorize(
        ActionRequest(
            action="future_tool_action",
            risk_class=RiskClass.READ,
            details={"auxiliary_action": True},
        ),
        task=None,
    )

    assert decision.allowed is False
    assert decision.owner == "agent_policy"
    assert decision.side_effect_class == "unknown"


def test_command_spawn_daemon_forwards_task_id_separately_from_name(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class Broker:
        def authorize_auxiliary_action(
            self, action: str, *, endpoint: str = "", task_id: str = ""
        ) -> dict[str, object]:
            captured["authorized_action"] = action
            captured["policy_task_id"] = task_id
            return {"allowed": True}

        def spawn_daemon(
            self,
            command: str,
            cwd: str,
            *,
            name: str = "",
            env: dict[str, str] | None = None,
            task_id: str = "",
        ) -> dict[str, object]:
            captured.update({"command": command, "cwd": cwd, "name": name, "env": env, "task_id": task_id})
            return {"success": True}

    services = LocalAIServices.__new__(LocalAIServices)
    services.commands = Broker()
    services.agent_state = None

    result = services.command(
        {
            "action": "spawn_daemon",
            "command": "python -c pass",
            "cwd": str(tmp_path),
            "name": "named-daemon",
            "task_id": "task-owned",
        },
        "agent",
    )

    assert result["success"] is True
    assert captured["task_id"] == "task-owned"
    assert captured["name"] == "named-daemon"
    assert captured["authorized_action"] == "spawn_daemon"
    assert captured["policy_task_id"] == "task-owned"


def test_auxiliary_authorization_resolves_registered_task_before_policy(tmp_path: Path) -> None:
    registered_task = type("RegisteredTask", (), {"task_id": "task-owned"})()
    captured: dict[str, object] = {}

    class TaskStore:
        def get(self, task_id: str) -> object | None:
            captured["task_id"] = task_id
            return registered_task if task_id == "task-owned" else None

    class Policy:
        def authorize(
            self, request: ActionRequest, task: object | None, grant: CapabilityGrant | None = None
        ) -> PolicyDecision:
            captured["task"] = task
            captured["authorized_task_id"] = getattr(task, "task_id", None)
            return PolicyDecision(allowed=True, side_effect_class="process_lifecycle")

    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path)}}, artifacts=None, repo_state=None
    )
    broker.set_task_store(TaskStore())
    broker.set_policy_engine(Policy())

    result = broker.authorize_auxiliary_action("spawn_daemon", task_id="task-owned")

    assert result["allowed"] is True
    assert captured["task_id"] == "task-owned"
    assert captured["task"] is registered_task
    assert captured["authorized_task_id"] == "task-owned"


def test_auxiliary_authorization_rejects_unregistered_task(tmp_path: Path) -> None:
    class TaskStore:
        def get(self, task_id: str) -> None:
            return None

    class Policy:
        def authorize(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("policy must not authorize an unregistered task")

    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path)}}, artifacts=None, repo_state=None
    )
    broker.set_task_store(TaskStore())
    broker.set_policy_engine(Policy())

    result = broker.authorize_auxiliary_action("spawn_daemon", task_id="missing")

    assert result["allowed"] is False
    assert result["terminal"] is True
    assert result["side_effect_class"] == "process_lifecycle"
    assert result["reason"] == "task context missing or mismatched for auxiliary action"


def test_services_command_authorizes_run_before_broker_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {"enabled": True},
            "agent_policy": {
                "enabled": True,
                "allow_developer_authorized_mutations": False,
            },
        },
        artifacts=None,
        repo_state=None,
    )
    broker.set_policy_engine(PolicyEngine())
    dispatched: list[str] = []
    monkeypatch.setattr(
        broker,
        "run",
        lambda command, *_args, **_kwargs: dispatched.append(command) or {"success": True},
    )
    services = LocalAIServices.__new__(LocalAIServices)
    services.commands = broker
    services.agent_state = None

    result = services.command(
        {
            "action": "run",
            "command": 'python -c "print(1)"',
            "cwd": str(tmp_path),
            "task_id": "task-owned",
            "force": True,
        },
        "agent",
    )

    assert result["success"] is False
    assert result["policy_blocked"] is True
    assert result["policy"]["allowed"] is False
    assert result["policy"]["owner"] == "agent_policy"
    assert dispatched == []


def test_services_command_rejects_unknown_action_before_run_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}}, artifacts=None, repo_state=None)
    broker.set_policy_engine(PolicyEngine())
    dispatched: list[str] = []
    monkeypatch.setattr(
        broker,
        "run",
        lambda command, *_args, **_kwargs: dispatched.append(command) or {"success": True},
    )
    services = LocalAIServices.__new__(LocalAIServices)
    services.commands = broker
    services.agent_state = None

    result = services.command(
        {"action": "future_action", "command": "must-not-run", "cwd": str(tmp_path)},
        "agent",
    )

    assert result["success"] is False
    assert result["policy_blocked"] is True
    assert result["policy"]["side_effect_class"] == "unknown"
    assert dispatched == []


def test_disabled_auxiliary_policy_denies_known_action(policy: PolicyEngine) -> None:
    disabled_policy = PolicyEngine(auxiliary_actions_enabled=False)
    decision = disabled_policy.authorize(
        ActionRequest(
            action="format",
            risk_class=RiskClass.READ,
        ),
        task=None,
    )

    assert decision.allowed is False
    assert decision.side_effect_class == "workspace_write"


@pytest.mark.parametrize(
    ("action", "side_effect_class"),
    [("daemon_status", "process_status"), ("mock_server_status", "process_status")],
)
def test_auxiliary_status_actions_keep_read_access_and_policy_metadata(
    policy: PolicyEngine, action: str, side_effect_class: str
) -> None:
    decision = policy.authorize(
        ActionRequest(action=action, risk_class=RiskClass.WRITE), task=None
    )

    assert decision.allowed is True
    assert decision.owner == "agent_policy"
    assert decision.side_effect_class == side_effect_class


@pytest.mark.parametrize("endpoint", ["mcp", "http", "cli", "direct"])
def test_alternate_entry_points_cannot_downgrade_auxiliary_action(
    policy: PolicyEngine, endpoint: str
) -> None:
    decision = policy.authorize(
        ActionRequest(
            action="mock_server_start",
            risk_class=RiskClass.READ,
            details={"endpoint": endpoint},
        ),
        task=None,
    )

    assert decision.allowed is False
    assert decision.side_effect_class == "network_listener"


def test_default_policy_settings_match_packaged_defaults() -> None:
    root = Path(__file__).resolve().parents[1]
    with (root / "defaults.toml").open("rb") as file:
        root_defaults = tomllib.load(file)
    with (root / "src/local_ai_hub/defaults.toml").open("rb") as file:
        package_defaults = tomllib.load(file)

    expected = {
        "enabled": True,
        "deny_unknown_auxiliary_actions": True,
        "allow_developer_authorized_mutations": True,
    }
    assert root_defaults["agent_policy"] == expected
    assert package_defaults["agent_policy"] == expected
