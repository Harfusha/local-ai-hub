from types import SimpleNamespace

import pytest

from local_ai_hub import http_server
from local_ai_hub.config import ConfigError, validate_config


def _handler(monkeypatch, security=None, token=None, peer="127.0.0.1"):
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(config={"security": security or {}}),
    )
    handler = SimpleNamespace(
        headers={"X-LocalAI-Token": token or ""},
        command="GET",
        path="/api/metrics",
        client_address=(peer, 1234),
    )
    return handler


def test_loopback_access_ignores_legacy_hub_token_header(monkeypatch):
    handler = _handler(monkeypatch)
    assert http_server.Handler._authorized(handler, action="dashboard:read") is True


def test_remote_peer_is_rejected_even_with_legacy_hub_token_header(monkeypatch):
    handler = _handler(monkeypatch, token="ignored-secret", peer="203.0.113.7")
    assert http_server.Handler._authorized(handler, action="dashboard:read") is False


def test_retired_user_credentials_are_rejected_by_config():
    with pytest.raises(ConfigError, match="security.users was removed"):
        validate_config({"security": {
            "users": {"viewer": {"token": "viewer-secret", "permissions": ["dashboard:read"]}},
        }})


@pytest.mark.parametrize("field", ["api_token", "supervisor_token", "action_tokens", "api_token_permissions"])
def test_retired_hub_auth_configuration_is_rejected(field):
    with pytest.raises(ConfigError, match="was removed"):
        validate_config({"security": {field: "legacy-value"}})


def test_security_config_rejects_duplicate_credentials_and_retired_user_scopes():
    with pytest.raises(ConfigError, match="security.users was removed"):
        validate_config({"security": {
            "users": {"viewer": {"token": "viewer-secret", "permissions": ["dashboard:admin"]}},
        }})


def test_empty_or_false_retired_auth_fields_are_still_rejected():
    for value in (None, "", False, {}):
        with pytest.raises(ConfigError, match="was removed"):
            validate_config({"security": {"api_token": value}})


@pytest.mark.parametrize("bind", ["0.0.0.0", "localhost", "::1"])
def test_network_security_rejects_any_bind_except_ipv4_loopback(bind):
    with pytest.raises(RuntimeError, match="127.0.0.1"):
        http_server.validate_network_security(
            {
                "server": {"bind": bind},
                "security": {
                    "api_token": "long-enough-service-secret",
                },
            }
        )


def test_network_security_accepts_only_ipv4_loopback():
    http_server.validate_network_security({"server": {"bind": "127.0.0.1"}})


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/api/metrics", "dashboard:read"),
        ("HEAD", "/api/status", "dashboard:read"),
        ("GET", "/api/agent-state/tasks", "agent_tasks:read"),
        ("GET", "/api/delegate", "api:read"),
        ("POST", "/api/admin/mode", "admin:write"),
    ],
)
def test_http_route_maps_to_least_privilege_permission(method, path, expected):
    handler = SimpleNamespace(command=method, path=path)

    assert http_server.Handler._required_permission(handler) == expected


@pytest.mark.parametrize("retired_value", [None, {}, False])
def test_config_redaction_rejects_retired_users_by_presence(retired_value):
    with pytest.raises(ValueError, match="security.users was removed"):
        http_server._redact_config_secrets({"security": {"users": retired_value}})


def test_config_validation_rejects_retired_auth_fields_after_mutation():
    config = {"security": {"api_token": "secret"}}
    with pytest.raises(ConfigError, match="security.api_token was removed"):
        validate_config(config)
    config["security"].pop("api_token")
    config["security"]["users"] = False

    with pytest.raises(ConfigError, match="security.users was removed"):
        validate_config(config)
