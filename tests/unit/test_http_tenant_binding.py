from email.message import Message
from types import SimpleNamespace

import pytest

from local_ai_hub import http_server


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


def test_authenticated_principal_tenant_is_used_before_configured_fallback(monkeypatch):
    handler = _handler(monkeypatch)
    handler._authorization_tenant = "authenticated-user-tenant"

    assert handler._bind_principal_tenant()
    assert handler._authorization_tenant == "authenticated-user-tenant"


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


def test_obsolete_tenant_header_is_rejected_before_authentication(monkeypatch):
    handler = _handler(monkeypatch)
    handler.command = "POST"
    handler.headers["X-Tenant-ID"] = "caller-selected-tenant"
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))
    handler._validate_host_and_origin = lambda: pytest.fail(
        "obsolete header must stop before auth"
    )

    assert not handler._require_authorized()
    assert responses[0][0] == 400
    assert responses[0][1]["error_code"] == "unsupported_tenant_header"
