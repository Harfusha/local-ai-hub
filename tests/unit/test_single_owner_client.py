"""SDK requests preserve credentials and scopes without tenant identity."""

import pytest

from local_ai_hub import client as client_module
from local_ai_hub.client import HubClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.delenv("LOCAL_AI_TENANT", raising=False)
    monkeypatch.setattr(client_module, "load_config", lambda *_args, **_kwargs: {
        "server": {"port": 11435},
        "security": {"api_token": "owner-secret", "allowed_roots": [str(tmp_path)]},
    })
    instance = HubClient(auto_start=False)
    yield instance
    instance.close()


@pytest.mark.parametrize("method", ["request", "post", "get"])
@pytest.mark.parametrize("value", [None, "", False, "former-owner"])
def test_retired_public_arguments_reject_by_presence(client, method, value):
    with pytest.raises(TypeError, match="tenant"):
        getattr(client, method)("/api/status", tenant=value)


def test_retired_constructor_argument_cannot_shift_to_config_path():
    with pytest.raises(TypeError, match="tenant"):
        HubClient(tenant=None)
    with pytest.raises(TypeError):
        HubClient("former-owner")


@pytest.mark.parametrize("value", [None, "", False, "former-owner"])
def test_payload_tenant_rejects_before_network(client, value):
    result = client.post("/api/delegate", {"task": "example", "tenant": value})
    assert result["success"] is False
    assert result["request_not_sent"] is True
    assert result["operation_not_started"] is True


def test_query_tenant_rejects_even_when_empty(client):
    result = client.get("/api/status?tenant=")
    assert result["success"] is False
    assert result["request_not_sent"] is True


@pytest.mark.parametrize("method", ["request", "post", "get"])
def test_requests_retain_api_token_without_tenant_header(client, monkeypatch, method):
    sent = []

    def open_request(verb, path, body, headers, timeout, **options):
        sent.append((verb, dict(headers)))
        return b'{"success":true}'

    monkeypatch.setattr(client, "_open", open_request)
    result = getattr(client, method)("/api/status")
    assert result["success"] is True
    assert len(sent) == 1
    assert sent[0][1]["X-LocalAI-Token"] == "owner-secret"
    assert "X-LocalAI-Tenant" not in sent[0][1]
    assert "X-Tenant-ID" not in sent[0][1]
    assert not hasattr(client, "tenant")


@pytest.mark.parametrize("scope", ["repository", "clone", "worktree", "branch", "task"])
def test_scoped_memory_still_requires_repository_root(client, scope):
    result = client.post("/api/agent-state/memory", {"action": "find", "scope": scope})
    assert result["success"] is False
    assert result["error_code"] == "root_required"


def test_owner_global_memory_does_not_acquire_a_synthetic_partition(client):
    assert client._request_scope("/api/agent-state/memory", {"scope": "global"}) is None


@pytest.mark.parametrize("scope", [None, False, "GLOBAL", " global ", "repo", [], {}])
def test_memory_scope_cannot_coerce_or_fall_back(client, scope):
    result = client._request_scope("/api/agent-state/memory", {"scope": scope})
    assert result["success"] is False
    assert result["error_code"] == "invalid_scope"


def test_conflicting_memory_scopes_reject(client):
    result = client._request_scope("/api/agent-state/memory", {
        "scope": "global", "record": {"scope": "repository"},
    })
    assert result["success"] is False
    assert result["error_code"] == "invalid_scope"


def test_repository_memory_rejects_outside_allowed_root(client, tmp_path):
    result = client._request_scope("/api/agent-state/memory", {
        "scope": "repository", "root": str(tmp_path.parent),
    })
    assert result["success"] is False
    assert result["error_code"] == "root_not_allowed"


def test_task_root_mismatch_rejects_before_network(client, tmp_path):
    nested = tmp_path / "other-project"
    nested.mkdir()
    result = client.post("/api/agent-state/tasks", {
        "action": "get", "root": str(tmp_path),
        "repo_root": str(nested),
        "context": {"repository_id": "logical-project-id"},
    })
    assert result["success"] is False
    assert result["error_code"] == "root_not_allowed"
