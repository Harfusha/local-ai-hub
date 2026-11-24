"""Retired HTTP identity configuration is rejected without weakening auth."""

from pathlib import Path

import pytest

from local_ai_hub import http_server
from local_ai_hub.config import ConfigError, validate_config


@pytest.mark.parametrize("retired", ["users", "api_token_tenant", "api_token_principal"])
@pytest.mark.parametrize("value", [None, False, ""])
def test_retired_security_identity_config_rejects_presence(retired, value):
    with pytest.raises(ConfigError, match=retired):
        validate_config({"security": {retired: value}})


def test_http_identity_module_is_removed():
    package_dir = Path(__file__).parents[2] / "src" / "local_ai_hub"
    assert not (package_dir / "http_identity.py").exists()


def test_api_token_and_permissions_are_retired():
    with pytest.raises(ConfigError, match="security.api_token was removed"):
        validate_config({"security": {"api_token": "secret"}})
    with pytest.raises(ConfigError, match="security.api_token_permissions was removed"):
        validate_config({"security": {"api_token_permissions": ["read", "write"]}})


def test_agent_header_fallback_does_not_recurse():
    handler = object.__new__(http_server.Handler)
    handler.headers = {"X-LocalAI-Agent": "codex"}

    assert handler._agent() == "codex"


@pytest.mark.parametrize(
    "provider",
    ["codex", "antigravity", "gemini_cli", "claude", "cursor", "windsurf", "copilot", "opencode", "devin"],
)
def test_provider_identity_header_cannot_authorize_remote_admin_request(monkeypatch, provider):
    monkeypatch.setattr(http_server, "APP", type("App", (), {"config": {"security": {}}})())
    handler = object.__new__(http_server.Handler)
    handler.headers = {"X-LocalAI-Agent": provider}
    handler.path = "/api/admin/config"
    handler.command = "POST"
    handler.client_address = ("192.0.2.10", 12345)

    assert handler._agent() == provider
    assert handler._required_permission() == "admin:write"
    assert handler._authorized() is False
    assert handler._authorization_actor == "unrecognized"
    assert handler._authorization_permissions == frozenset()


@pytest.mark.parametrize("provider", ["codex", "antigravity", "gemini_cli", "claude", "cursor", "windsurf", "copilot", "opencode", "devin"])
def test_provider_identity_does_not_change_single_local_owner(monkeypatch, provider):
    monkeypatch.setattr(http_server, "APP", type("App", (), {"config": {"security": {}}})())
    handler = object.__new__(http_server.Handler)
    handler.headers = {"X-LocalAI-Agent": provider}
    handler.path = "/api/admin/config"
    handler.command = "POST"
    handler.client_address = ("127.0.0.1", 12345)

    assert handler._authorized() is True
    assert handler._authorization_actor == "local"
    assert handler._authorization_permissions == frozenset()
