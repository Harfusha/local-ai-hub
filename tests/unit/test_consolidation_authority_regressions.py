"""Classification and artifact authority regressions; never execute inline code."""
from types import SimpleNamespace

import pytest

from local_ai_hub.commands import CommandBroker
from local_ai_hub import http_server, operation_contracts


@pytest.mark.parametrize("code", [
    "import os; os.write(3, b'unsafe')",
    "import os as other; other.write(3, b'unsafe')",
    "import os; os.read(3, 1)",
    "import sys; sys = 1; sys.stdout.write('unsafe')",
])
def test_module_methods_do_not_inherit_safe_string_method_permissions(code):
    broker = object.__new__(CommandBroker)
    broker.config = {"commands": {"allow_unknown": False}}
    result = broker.classify(["python", "-c", code])
    assert result["allowed"] is False
    assert result["cacheable"] is False


@pytest.mark.parametrize("code", [
    "import sys; sys.stdout.write('safe')",
    "import sys; sys.stdout.buffer.write(b'safe')",
])
def test_explicit_standard_output_calls_remain_allowed(code):
    broker = object.__new__(CommandBroker)
    broker.config = {"commands": {"allow_unknown": False}}
    assert broker.classify(["python", "-c", code])["allowed"] is True


@pytest.mark.parametrize("payload,method", [
    ({"artifact_id": "artifact"}, "get"),
    ({"artifact_id": "artifact", "binary": True}, "get_binary"),
    ({"artifact_id": "artifact", "slices": [{"offset": 0, "max_chars": 10}]}, "get_slices"),
])
def test_artifact_handler_rejects_retired_tenant_selector(monkeypatch, payload, method):
    calls = []

    def retrieve(*args, **kwargs):
        calls.append((args, kwargs))
        return {"success": True}

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(artifacts=SimpleNamespace(**{method: retrieve})))
    handler = object.__new__(http_server.Handler)
    handler.headers = {}
    handler._send = lambda status, data: None
    payload = {**payload, "tenant": None}
    responses = []
    handler._send = lambda status, data: responses.append((status, data))
    handler._handle_post_artifact_get(payload)
    assert responses[0][0] == 400
    assert calls == []


def test_binary_artifact_contract_keeps_identity_and_checksum_fields():
    variants = operation_contracts._artifact_output_variants("get")
    binary = next(item for item in variants if "binary_payload" in item.get("properties", {}))
    assert {"identity", "sha256", "checksum", "kind", "encoding"} <= set(binary["required"])
