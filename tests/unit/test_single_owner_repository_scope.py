"""Single-owner incident boundaries; no runtime tenant partition."""

import pytest

from local_ai_hub.repository_scope import (
    RepositoryScopeError,
    authorized_repository_root,
    reject_retired_tenancy_fields,
)


def test_sdk_task_preflight_keeps_project_id_separate_from_physical_root(tmp_path):
    from local_ai_hub.client import HubClient

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    client = HubClient.__new__(HubClient)
    client.config = {"security": {"allowed_roots": [str(allowed)]}}

    result = client._request_scope(
        "/api/agent-state/tasks",
        {"root": str(allowed), "context": {"repository_id": "coordination-id"}},
    )

    assert result is None


def test_sdk_task_preflight_still_confines_physical_root_and_validates_identity(tmp_path):
    from local_ai_hub.client import HubClient

    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    client = HubClient.__new__(HubClient)
    client.config = {"security": {"allowed_roots": [str(allowed)]}}

    outside_result = client._request_scope(
        "/api/agent-state/tasks",
        {"root": str(outside), "context": {"repository_id": "coordination-id"}},
    )
    malformed_identity = client._request_scope(
        "/api/agent-state/tasks",
        {"root": str(allowed), "context": {"repository_id": " coordination-id "}},
    )

    assert outside_result is not None and outside_result["error_code"] == "root_not_allowed"
    assert malformed_identity is not None and malformed_identity["error_code"] == "invalid_identity"


def test_root_confinement_preserves_repository_boundaries(tmp_path):
    allowed = tmp_path / "allowed"
    other = tmp_path / "other"
    allowed.mkdir()
    other.mkdir()
    config = {"security": {"api_token": "owner-secret", "allowed_roots": [str(allowed)]}}
    assert authorized_repository_root(config, str(allowed)) == str(allowed.resolve())
    with pytest.raises(RepositoryScopeError, match="outside allowed_roots"):
        authorized_repository_root(config, str(other))


def test_token_does_not_remove_root_confinement(tmp_path):
    with pytest.raises(RepositoryScopeError, match="outside allowed_roots"):
        authorized_repository_root({"security": {"api_token": "owner-secret"}}, str(tmp_path))


@pytest.mark.parametrize("root", [None, "", ".", False, 1, "C:/invalid\x00root"])
def test_explicit_absolute_root_required(root):
    with pytest.raises(RepositoryScopeError):
        authorized_repository_root({}, root)


@pytest.mark.parametrize("value", [None, "", False, "old-partition"])
@pytest.mark.parametrize("field", ["tenant", "tenant_key"])
@pytest.mark.parametrize("container", ["payload", "record", "provenance", "metadata"])
def test_retired_fields_reject_by_presence(value, field, container):
    content = {field: value}
    payload = content if container == "payload" else {container: content}
    with pytest.raises(RepositoryScopeError, match="retired tenancy field"):
        reject_retired_tenancy_fields(payload)


def test_nested_record_provenance_rejects_retired_identity():
    with pytest.raises(RepositoryScopeError, match="record.provenance.tenant"):
        reject_retired_tenancy_fields({"record": {"provenance": {"tenant": None}}})


def test_free_text_does_not_become_identity():
    reject_retired_tenancy_fields({"message": "tenant removal", "metadata": {"agent": "writer"}})


def test_cyclic_input_is_bounded():
    payload = {}
    payload["record"] = payload
    payload["metadata"] = payload
    reject_retired_tenancy_fields(payload)


@pytest.mark.parametrize("header", ["X-LocalAI-Tenant", "X-Tenant-ID"])
def test_http_incident_rejects_even_empty_retired_header(monkeypatch, tmp_path, header):
    from email.message import Message
    from types import SimpleNamespace

    from local_ai_hub import http_server

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={}))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.headers = Message()
    handler.headers[header] = ""
    sent = []
    handler._send = lambda status, payload: sent.append((status, payload))
    assert handler._bind_incident_payload({"root": str(tmp_path)}) is False
    assert sent[0][0] == 400
    assert sent[0][1]["error_code"] == "retired_tenant_header"


def test_http_incident_binds_repository_without_partition(monkeypatch, tmp_path):
    from email.message import Message
    from types import SimpleNamespace

    from local_ai_hub import http_server

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={
        "security": {"api_token": "owner-secret", "allowed_roots": [str(tmp_path)]},
    }))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.headers = Message()
    payload = {"root": str(tmp_path)}
    assert handler._bind_incident_payload(payload)
    assert payload == {"root": str(tmp_path.resolve())}
    assert handler._authorization_root == str(tmp_path.resolve())
    assert "_authorization_tenant" not in handler.__dict__


@pytest.mark.parametrize("supplied,permission,expected", [
    ("a" * 32, "read", True),
    ("wrong-token", "read", False),
    ("a" * 32, "write", False),
])
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_token_and_permission_checks_remain_independent_of_identity(
    monkeypatch, supplied, permission, expected, method,
):
    from email.message import Message
    from types import SimpleNamespace

    from local_ai_hub import http_server

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {
        "api_token": "a" * 32, "api_token_permissions": ["read"],
    }}))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.command = method
    handler.headers = Message()
    handler.headers["X-LocalAI-Token"] = supplied
    handler.client_address = ("127.0.0.1", 10000)
    assert handler._authorized(action=f"files:{permission}", permission=permission) is expected
    if expected:
        assert handler._authorization_actor == "api_token"
