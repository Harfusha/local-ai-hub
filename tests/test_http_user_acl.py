from types import SimpleNamespace

import pytest

from local_ai_hub import http_server
from local_ai_hub.config import ConfigError, validate_config


def _handler(monkeypatch, security, token):
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(config={"security": security}),
    )
    handler = SimpleNamespace(
        headers={"X-LocalAI-Token": token or ""},
        command="GET",
        path="/api/metrics",
    )
    handler._configured_principal_tenant = lambda: http_server.Handler._configured_principal_tenant(handler)
    handler._principal_tenant = lambda: http_server.Handler._principal_tenant(handler)
    return handler


def test_empty_or_missing_credentials_fail_closed(monkeypatch):
    handler = _handler(monkeypatch, {"api_token": ""}, None)

    assert http_server.Handler._authorized(handler, action="dashboard:read") is False


def test_invalid_credentials_fail_closed(monkeypatch):
    handler = _handler(monkeypatch, {"api_token": "service-secret"}, "wrong-secret")

    assert http_server.Handler._authorized(handler, action="dashboard:read") is False


def test_per_user_credential_gets_only_configured_actions(monkeypatch):
    handler = _handler(
        monkeypatch,
        {
            "users": {
                "viewer": {
                    "token": "viewer-secret",
                    "permissions": ["dashboard:read"],
                    "tenant": "viewer-tenant",
                }
            }
        },
        "viewer-secret",
    )

    assert http_server.Handler._authorized(handler, action="dashboard:read") is True
    assert handler._authorization_actor == "viewer"
    assert handler._authorization_permissions == frozenset({"dashboard:read"})
    assert handler._authorization_tenant == "viewer-tenant"
    assert http_server.Handler._authorized(handler, action="admin:write") is False


def test_service_supervisor_and_user_credentials_remain_distinct(monkeypatch):
    security = {
        "api_token": "service-secret",
        "supervisor_token": "supervisor-secret",
        "users": {
            "operator": {
                "token": "operator-secret",
                "permissions": ["admin:write"],
            }
        },
    }
    service = _handler(monkeypatch, security, "service-secret")
    supervisor = _handler(monkeypatch, security, "supervisor-secret")
    user = _handler(monkeypatch, security, "operator-secret")

    assert http_server.Handler._authorized(service, action="admin:write") is True
    assert service._authorization_actor == "service"
    assert service._authorization_tenant == "api-token-default"
    assert http_server.Handler._authorized(supervisor, action="admin:write") is True
    assert supervisor._authorization_actor == "supervisor"
    assert http_server.Handler._authorized(user, action="admin:write") is True
    assert user._authorization_actor == "operator"


def test_duplicate_credentials_fail_closed(monkeypatch):
    handler = _handler(
        monkeypatch,
        {
            "api_token": "shared-secret",
            "users": {
                "viewer": {
                    "token": "shared-secret",
                    "permissions": ["dashboard:read"],
                }
            },
        },
        "shared-secret",
    )

    assert http_server.Handler._authorized(handler, action="dashboard:read") is False


def test_security_config_rejects_duplicate_credentials_and_bad_user_scopes():
    with pytest.raises(ConfigError, match="credentials must be unique"):
        validate_config({"security": {
            "api_token": "shared-secret",
            "users": {"viewer": {"token": "shared-secret", "permissions": ["dashboard:read"]}},
        }})

    with pytest.raises(ConfigError, match="resource:read/write scopes"):
        validate_config({"security": {
            "users": {"viewer": {"token": "viewer-secret", "permissions": ["dashboard:admin"]}},
        }})


def test_diagnostic_config_redacts_every_authentication_secret():
    redacted = http_server._redact_config_secrets({"security": {
        "api_token": "api-secret",
        "supervisor_token": "supervisor-secret",
        "action_tokens": {"dashboard:read": "action-secret"},
        "users": {"viewer": {"token": "user-secret", "permissions": ["dashboard:read"]}},
    }})

    security = redacted["security"]
    assert security["api_token"] == "***configured***"
    assert security["supervisor_token"] == "***configured***"
    assert security["action_tokens"]["dashboard:read"] == "***configured***"
    assert security["users"]["viewer"]["token"] == "***configured***"


@pytest.mark.parametrize("bind", ["0.0.0.0", "localhost", "::1"])
def test_network_security_rejects_any_bind_except_ipv4_loopback(bind):
    with pytest.raises(RuntimeError, match="127.0.0.1"):
        http_server.validate_network_security(
            {
                "server": {"bind": bind},
                "security": {
                    "allow_remote": True,
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
