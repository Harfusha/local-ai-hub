from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from local_ai_hub.agent_policy import (
    ActionRequest,
    CapabilityGrant,
    PolicyEngine,
    RiskClass,
)
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
