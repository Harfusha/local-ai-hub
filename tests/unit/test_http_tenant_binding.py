from email.message import Message
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub import http_server, project_config, state_paths


def _handler(monkeypatch):
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {}}))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/agent-state/tasks"
    handler.headers = Message()
    return handler


def test_tokenless_http_tenant_identity_comes_from_stable_principal(monkeypatch):
    handler = _handler(monkeypatch)

    assert handler._bind_principal_tenant()
    assert handler._authorization_tenant == "api-token-default"
    assert handler._tenant() == "api-token-default"


def test_canonical_tenant_header_is_only_a_claim(monkeypatch):
    handler = _handler(monkeypatch)
    handler.headers["X-LocalAI-Tenant"] = "caller-selected-tenant"
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    assert not handler._bind_principal_tenant()
    assert responses[0][0] == 403
    assert responses[0][1]["error_code"] == "tenant_binding_mismatch"


def test_artifact_get_rejects_caller_selected_tenant(monkeypatch):
    calls = []
    artifacts = SimpleNamespace(
        get=lambda *args, **kwargs: calls.append((args, kwargs)) or {"success": True}
    )
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {}}, artifacts=artifacts))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.headers = Message()
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    handler._handle_post_artifact_get(
        {"artifact_id": "artifact-a", "tenant": "caller-selected-tenant"},
        tenant="server-bound-tenant",
    )

    assert responses[0][0] == 400
    assert calls == []


def test_artifact_get_uses_server_bound_tenant(monkeypatch):
    calls = []
    artifacts = SimpleNamespace(
        get=lambda *args, **kwargs: calls.append((args, kwargs)) or {"success": True}
    )
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {}}, artifacts=artifacts))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.headers = Message()
    handler._send = lambda _status, _payload: None

    handler._handle_post_artifact_get(
        {"artifact_id": "artifact-a"},
        tenant="server-bound-tenant",
    )

    assert calls == [(("artifact-a", 0, 6000, ""), {"tenant": "server-bound-tenant"})]


def test_artifact_list_rejects_caller_selected_tenant(monkeypatch):
    calls = []
    artifacts = SimpleNamespace(
        list=lambda **kwargs: calls.append(kwargs) or []
    )
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {}}, artifacts=artifacts))
    handler = http_server.Handler.__new__(http_server.Handler)
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    handler._handle_post_artifact_list(
        {"tenant": "caller-selected-tenant", "limit": 10},
        tenant="server-bound-tenant",
    )

    assert responses[0][0] == 400
    assert calls == []


def test_artifact_list_uses_only_authenticated_tenant(monkeypatch):
    calls = []
    artifacts = SimpleNamespace(
        list=lambda **kwargs: calls.append(kwargs) or []
    )
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {}}, artifacts=artifacts))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler._send = lambda _status, _payload: None

    handler._handle_post_artifact_list({"limit": 15}, tenant="server-bound-tenant")

    assert calls == [{"tenant": "server-bound-tenant", "limit": 15}]


def test_artifact_list_fails_closed_without_authenticated_tenant(monkeypatch):
    calls = []
    artifacts = SimpleNamespace(list=lambda **kwargs: calls.append(kwargs) or [])
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {}}, artifacts=artifacts))
    handler = http_server.Handler.__new__(http_server.Handler)
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    handler._handle_post_artifact_list({}, tenant=" ")

    assert responses[0][0] == 403
    assert calls == []


@pytest.mark.parametrize("limit", [True, 0, -1, "10"])
def test_artifact_list_rejects_coerced_or_invalid_limits(monkeypatch, limit):
    calls = []
    artifacts = SimpleNamespace(list=lambda **kwargs: calls.append(kwargs) or [])
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {}}, artifacts=artifacts))
    handler = http_server.Handler.__new__(http_server.Handler)
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    handler._handle_post_artifact_list({"limit": limit}, tenant="server-bound-tenant")

    assert responses[0][0] == 400
    assert calls == []


def test_lease_claim_rejects_tenant_override_and_non_string_paths(monkeypatch):
    calls = []
    leases = SimpleNamespace(claim_batch=lambda *args, **kwargs: calls.append((args, kwargs)) or {"success": True})
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {}}, leases=leases))
    handler = http_server.Handler.__new__(http_server.Handler)
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    handler._handle_post_lease_claim(
        {"tenant": "caller-selected-tenant", "root": "repo", "paths": ["src/a.py"]},
        tenant="server-bound-tenant",
    )
    handler._handle_post_lease_claim(
        {"root": "repo", "paths": [123]}, tenant="server-bound-tenant",
    )
    handler._handle_post_lease_claim(
        {"root": "repo", "paths": ["src/a.py"], "ttl_seconds": True},
        tenant="server-bound-tenant",
    )

    assert [response[0] for response in responses] == [400, 400, 400]
    assert calls == []


def test_lease_claim_uses_only_authenticated_tenant(monkeypatch):
    calls = []
    leases = SimpleNamespace(claim_batch=lambda *args, **kwargs: calls.append((args, kwargs)) or {"success": True})
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {}}, leases=leases))
    monkeypatch.setattr(http_server, "_lease_coordination_id", lambda _root: "repo-coordination")
    handler = http_server.Handler.__new__(http_server.Handler)
    handler._send = lambda _status, _payload: None

    handler._handle_post_lease_claim(
        {"root": "repo", "paths": ["src/a.py"], "ttl_seconds": 120, "purpose": "edit"},
        tenant="server-bound-tenant",
    )

    assert calls == [(("server-bound-tenant", "repo", ["src/a.py"], 120, "edit"), {"coordination_id": "repo-coordination"})]


def test_lease_release_requires_specific_id_and_authenticated_tenant(monkeypatch):
    calls = []
    leases = SimpleNamespace(release=lambda *args: calls.append(args) or {"success": True})
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {}}, leases=leases))
    handler = http_server.Handler.__new__(http_server.Handler)
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    handler._handle_post_lease_release({}, tenant="server-bound-tenant")
    handler._handle_post_lease_release(
        {"lease_id": "lease-1", "tenant": "caller-selected-tenant"}, tenant="server-bound-tenant",
    )
    handler._handle_post_lease_release({"lease_id": 123}, tenant="server-bound-tenant")
    handler._handle_post_lease_release(
        {"lease_id": "lease-1"}, tenant="server-bound-tenant",
    )

    assert [response[0] for response in responses] == [400, 400, 400, 200]
    assert calls == [("server-bound-tenant", "lease-1")]


@pytest.mark.parametrize("ttl_seconds", [True, "900", 0, -1])
def test_lease_renew_rejects_coercive_or_invalid_ttl(monkeypatch, ttl_seconds):
    calls = []
    leases = SimpleNamespace(renew=lambda *args: calls.append(args) or {"success": True})
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {}}, leases=leases))
    handler = http_server.Handler.__new__(http_server.Handler)
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    handler._handle_post_lease_renew(
        {"lease_id": "lease-1", "ttl_seconds": ttl_seconds}, tenant="server-bound-tenant",
    )

    assert responses[0][0] == 400
    assert calls == []


def test_authenticated_principal_tenant_is_used_before_configured_fallback(monkeypatch):
    handler = _handler(monkeypatch)
    handler._authorization_tenant = "authenticated-user-tenant"

    assert handler._bind_principal_tenant()
    assert handler._authorization_tenant == "authenticated-user-tenant"


def test_same_handler_reauthorization_discards_previous_user_and_root(
    tmp_path, monkeypatch
):
    second_root = tmp_path / "second"
    second_root.mkdir()
    handler = _handler(monkeypatch)
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            config={
                "security": {
                    "users": {
                        "user-one": {
                            "token": "first-token",
                            "tenant": "tenant-one",
                            "permissions": ["tasks:read"],
                        },
                        "user-two": {
                            "token": "second-token",
                            "tenant": "tenant-two",
                            "permissions": ["tasks:read"],
                        },
                    }
                }
            }
        ),
    )
    handler.headers["X-LocalAI-Token"] = "first-token"
    assert handler._authorized(permission="tasks:read")
    assert handler._bind_root_tenant(str(tmp_path)) == (
        str(tmp_path.resolve()),
        "tenant-one",
    )

    handler.headers.replace_header("X-LocalAI-Token", "second-token")
    assert handler._authorized(permission="tasks:read")
    assert handler._bind_root_tenant(str(second_root)) == (
        str(second_root.resolve()),
        "tenant-two",
    )


def test_tokenless_root_binding_uses_principal_instead_of_tenant_claim(
    tmp_path, monkeypatch
):
    handler = _handler(monkeypatch)
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    bound = handler._bind_root_tenant(str(tmp_path))
    assert bound == (str(tmp_path.resolve()), "api-token-default")
    other = tmp_path / "other"
    other.mkdir()
    assert handler._bind_root_tenant(str(other)) == (
        str(other.resolve()), "api-token-default"
    )

    assert handler._bind_root_tenant(str(tmp_path), ["caller-selected-tenant"]) is None
    assert responses[-1][0] == 403
    assert responses[-1][1]["error_code"] == "tenant_binding_mismatch"


def test_post_memory_repository_id_requires_server_resolved_root(tmp_path, monkeypatch):
    handler = _handler(monkeypatch)
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    assert not handler._bind_memory_payload(
        {
            "action": "get",
            "scope": "repository",
            "repository_id": "caller-selected-repository",
        }
    )
    assert responses[0][0] == 400
    assert responses[0][1]["error_code"] == "root_required"

    monkeypatch.setattr(
        project_config,
        "resolve_project_context",
        lambda requested, _state: SimpleNamespace(
            root=str(tmp_path), coordination_id="server-resolved-repository"
        ),
    )
    monkeypatch.setattr(state_paths, "configured_state_dir", lambda _config: tmp_path)
    assert handler._memory_project_identity(str(tmp_path)) == (
        str(Path(tmp_path).resolve(strict=True)),
        "server-resolved-repository",
    )


def test_configured_root_sandbox_requires_configured_principal(tmp_path, monkeypatch):
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            config={
                "security": {
                    "allowed_roots": [str(tmp_path)],
                    "tenant_derivation_key": "test-key",
                }
            }
        ),
    )
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/agent-state/tasks"
    handler.headers = Message()
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    assert handler._bind_root_tenant(
        str(tmp_path), require_configured_principal=True
    ) is None
    assert responses[0][0] == 403


def test_configured_root_sandbox_accepts_configured_principal(tmp_path, monkeypatch):
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            config={
                "security": {
                    "allowed_roots": [str(tmp_path)],
                    "tenant_derivation_key": "test-key",
                    "api_token_tenant": "configured-tenant",
                }
            }
        ),
    )
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/agent-state/tasks"
    handler.headers = Message()
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    bound = handler._bind_root_tenant(
        str(tmp_path), require_configured_principal=True
    )
    assert bound is not None
    assert bound[0] == str(tmp_path.resolve())
    assert bound[1] == handler._authorization_tenant
    assert not responses


def test_obsolete_tenant_header_is_rejected_after_host_validation(monkeypatch):
    handler = _handler(monkeypatch)
    handler.command = "POST"
    handler.headers["X-Tenant-ID"] = "caller-selected-tenant"
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))
    order = []
    handler._validate_host_and_origin = lambda: order.append("host") or True
    handler._authorized = lambda *args, **kwargs: pytest.fail(
        "obsolete header must stop before authentication"
    )

    assert not handler._require_authorized()
    assert order == ["host"]
    assert responses[0][0] == 400
    assert responses[0][1]["error_code"] == "unsupported_tenant_header"
