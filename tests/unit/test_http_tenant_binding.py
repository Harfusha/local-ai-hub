"""HTTP request metadata keeps repository and writer identity explicit."""
from email.message import Message
from types import SimpleNamespace

import pytest

from local_ai_hub import http_server


def _handler():
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/agent-state/memory"
    handler.headers = Message()
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))
    return handler, responses


@pytest.mark.parametrize("field", ["tenant", "tenant_id", "tenant_key", "tenant_scope"])
@pytest.mark.parametrize("value", [None, "", False])
def test_artifact_get_rejects_retired_identity_fields_by_presence(monkeypatch, field, value):
    calls = []
    artifacts = SimpleNamespace(get=lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(artifacts=artifacts))
    handler, responses = _handler()

    handler._handle_post_artifact_get({"artifact_id": "artifact-a", field: value})

    assert responses[0][0] == 400
    assert calls == []


def test_artifact_get_preserves_canonical_slice_metadata(monkeypatch):
    calls = []
    artifacts = SimpleNamespace(get=lambda *args, **kwargs: calls.append((args, kwargs)) or {"success": True})
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(artifacts=artifacts))
    handler, responses = _handler()

    handler._handle_post_artifact_get(
        {"artifact_id": "artifact-a", "offset": 12, "max_chars": 345, "section": "source"}
    )

    assert responses == [(200, {"success": True})]
    assert calls == [(("artifact-a",), {"offset": 12, "max_chars": 345, "section": "source"})]


@pytest.mark.parametrize("field", ["tenant", "tenant_id", "tenant_key", "tenant_scope"])
@pytest.mark.parametrize("value", [None, "", False])
def test_lease_claim_rejects_retired_identity_fields_by_presence(monkeypatch, tmp_path, field, value):
    calls = []
    leases = SimpleNamespace(claim_batch=lambda **kwargs: calls.append(kwargs) or {"success": True})
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(leases=leases))
    handler, responses = _handler()
    handler._bind_root = lambda root: root

    handler._handle_post_lease_claim(
        {"owner": "agent-a:execution-1", "root": str(tmp_path), "paths": ["src/a.py"], field: value}
    )

    assert responses[0][0] == 400
    assert calls == []


def test_lease_claim_preserves_repository_and_actual_writer_identity(monkeypatch, tmp_path):
    calls = []
    leases = SimpleNamespace(claim_batch=lambda **kwargs: calls.append(kwargs) or {"success": True})
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(leases=leases))
    monkeypatch.setattr(http_server, "_lease_coordination_id", lambda _root: "repo-coordination")
    handler, responses = _handler()
    handler._bind_root = lambda root: root

    handler._handle_post_lease_claim({
        "owner": "agent-a:execution-1", "root": str(tmp_path), "paths": ["src/a.py"],
        "ttl_seconds": 120, "purpose": "edit",
    })

    assert responses == [(200, {"success": True})]
    assert calls == [{
        "owner": "agent-a:execution-1", "root": str(tmp_path), "paths": ["src/a.py"],
        "ttl_seconds": 120, "purpose": "edit", "coordination_id": "repo-coordination",
    }]


@pytest.mark.parametrize("field", ["tenant", "tenant_id", "tenant_key", "tenant_scope"])
@pytest.mark.parametrize("value", [None, "", False])
def test_memory_binding_rejects_retired_identity_fields_by_presence(field, value):
    handler, responses = _handler()
    payload = {"action": "get", "scope": "session", "session_id": "session-a", field: value}

    assert not handler._bind_memory_payload(payload)
    assert responses[0][0] == 400


def test_session_memory_binding_preserves_explicit_session_identity():
    handler, responses = _handler()
    payload = {"action": "get", "scope": "session", "session_id": "session-a"}

    assert handler._bind_memory_payload(payload)
    assert payload["session_id"] == payload["scope_id"] == "session-a"
    assert not responses


def test_retired_tenant_header_is_rejected():
    handler, responses = _handler()
    handler.headers["X-LocalAI-Tenant"] = "caller-selected"

    assert not handler._reject_retired_tenant_headers()
    assert responses[0][0] == 400
    assert responses[0][1]["error_code"] == "retired_tenant_header"
