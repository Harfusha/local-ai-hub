from __future__ import annotations

import pytest

from local_ai_hub import commands
from local_ai_hub.services import LocalAIServices


RETIRED = (
    "http_probe", "record_mock", "replay_mock", "diff_hunk_stage",
    "test_flaky_detect", "webhook_replay", "mock_server_start",
    "mock_server_stop", "mock_server_status", "stash_save", "stash_restore",
)


@pytest.mark.parametrize("name", RETIRED)
def test_removed_features_have_no_backend_or_service_wrapper(name):
    assert not hasattr(commands.CommandBroker, name)
    assert not hasattr(LocalAIServices, name)


@pytest.mark.parametrize("action", RETIRED + ("flaky_detect",))
def test_internal_dispatch_cannot_reach_retired_features(action):
    services = object.__new__(LocalAIServices)
    services.commands = object()
    services._authorize_command_action = lambda *args, **kwargs: None
    result = services.command({"action": action})
    assert result["success"] is False
    assert "unknown" in result["error"].lower() or "unsupported" in result["error"].lower()


def test_retired_network_helpers_are_removed():
    for name in ("_NetworkPolicyError", "_PinnedHTTPConnection", "_PinnedHTTPSConnection",
                 "_perform_network_request", "_resolve_network_target", "_CASSETTE_NAME_RE"):
        assert not hasattr(commands, name)


def test_internal_workflow_primitives_are_retained():
    for name in ("run", "simulate_patch", "patch_and_verify"):
        assert callable(getattr(commands.CommandBroker, name))


def test_internal_workflow_discovery_remains_available(tmp_path):
    services = object.__new__(LocalAIServices)
    services.commands = object()
    services.deterministic = None
    services._authorize_command_action = lambda *args, **kwargs: None
    services.repo_profile = lambda root: {"success": True, "validation_commands": ["python -m pytest"]}
    result = services.command({"action": "discover", "root": str(tmp_path)})
    assert result["success"] is True
    assert result["validation_commands"] == ["python -m pytest"]
