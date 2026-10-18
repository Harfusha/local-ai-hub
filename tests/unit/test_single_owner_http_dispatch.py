"""HTTP and SDK contracts for single-owner dispatch."""

import importlib.util
import inspect

import pytest

from local_ai_hub.config import ConfigError, validate_config
from local_ai_hub.http_server import Handler
from local_ai_hub.repository_scope import RepositoryScopeError, reject_retired_tenancy_fields
from local_ai_hub.client import HubClient


@pytest.mark.parametrize("field", ["tenant", "tenant_key", "tenant_id", "tenant_scope", "tenant_identity", "tenant_partition"])
@pytest.mark.parametrize("value", [None, False, ""])
def test_wire_payload_rejects_retired_tenant_fields_by_presence(field, value):
    with pytest.raises(RepositoryScopeError, match="retired"):
        reject_retired_tenancy_fields({field: value})


@pytest.mark.parametrize("header", ["X-LocalAI-Tenant", "X-Tenant-ID"])
def test_http_dispatch_rejects_retired_tenant_headers(header):
    handler = object.__new__(Handler)
    handler.headers = {header: ""}
    sent = []
    handler._send = lambda status, payload: sent.append((status, payload))

    assert Handler._reject_retired_tenant_headers(handler) is False
    assert sent[0][0] == 400
    assert sent[0][1]["error_code"] == "retired_tenant_header"


def test_config_keeps_api_token_permissions_and_allowed_roots(tmp_path):
    validate_config({
        "security": {
            "api_token": "local-secret",
            "api_token_permissions": ["read", "write"],
            "allowed_roots": [str(tmp_path)],
        },
    })


@pytest.mark.parametrize("field", ["users", "api_token_tenant", "api_token_principal"])
@pytest.mark.parametrize("value", [None, False, ""])
def test_config_rejects_retired_principal_configuration_by_presence(field, value):
    with pytest.raises(ConfigError, match=field):
        validate_config({"security": {"api_token": "local-secret", field: value}})


def test_sdk_and_http_have_no_principal_selector():
    assert importlib.util.find_spec("local_ai_hub.http_identity") is None
    assert not hasattr(Handler, "_principal_tenant")
    for method in (HubClient.__init__, HubClient.request, HubClient.get, HubClient.post):
        assert "tenant" not in inspect.signature(method).parameters


def test_wire_scope_keeps_root_task_and_session_as_distinct_fields():
    payload = {"root": "C:/repo", "task_id": "task-7", "session_id": "session-9"}
    reject_retired_tenancy_fields(payload)
    assert payload == {"root": "C:/repo", "task_id": "task-7", "session_id": "session-9"}
