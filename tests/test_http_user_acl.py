from types import SimpleNamespace

import pytest

from local_ai_hub import http_server


def _handler(monkeypatch, security, token):
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(config={"security": security}),
    )
    return SimpleNamespace(
        headers={"X-LocalAI-Token": token or ""},
        command="GET",
        path="/api/metrics",
    )


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
    assert handler._principal == "viewer"
    assert handler._permissions == frozenset({"dashboard:read"})
    assert http_server.Handler._authenticated_tenant(handler) == "viewer-tenant"
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
    assert service._principal == "service"
    assert http_server.Handler._authenticated_tenant(service) == "http-default"
    assert http_server.Handler._authorized(supervisor, action="admin:write") is True
    assert supervisor._principal == "supervisor"
    assert http_server.Handler._authorized(user, action="admin:write") is True
    assert user._principal == "operator"


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
