"""Deferred canonical-input fixtures for incident HTTP and MCP actions."""
from __future__ import annotations

from local_ai_hub import http_server, mcp_server
from local_ai_hub.client import HubClient
from local_ai_hub.operation_contracts import operation_parameters_schema, validate_operation_arguments


FINGERPRINT = {
    "error_class": "TimeoutError",
    "operation_class": "command",
    "signature_hash": "a" * 64,
}


def _activate_coord(monkeypatch):
    from local_ai_hub.operational_mode import OperationalModeSnapshot

    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server.FEATURES, "agent_os", True)
    snapshot = OperationalModeSnapshot("active", 1, None)
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _state_dir: snapshot)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_kwargs: None)
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *_args, **_kwargs: None)


def _implementation():
    implementation = mcp_server.local_ai_coord
    while hasattr(implementation, "__wrapped__"):
        implementation = implementation.__wrapped__
    return implementation


class _FakeClient:
    def __init__(self):
        self.calls = []

    def post(self, path, payload, **kwargs):
        self.calls.append(("post", path, payload))
        return {"success": True}

    def coord(self, **payload):
        self.calls.append(("coord", payload))
        return {"success": True}


def test_http_incident_aliases_rejected_even_with_canonical_fields():
    payloads = [
        {"action": "decision", "fingerprint": FINGERPRINT, "state_revision": "r1", "revision": "old"},
        {"action": "record", "operation_class": "command", "root_cause": "cause", "reason": "old"},
        {"action": "find", "query": "timeout", "limit": 10, "key": "old"},
    ]
    for payload in payloads:
        payload.update(root=".", tenant="tenant-x")
        try:
            http_server.Handler._validate_payload("/api/agent-state/incidents", payload)
        except http_server.RequestBodyError:
            continue
        raise AssertionError(f"legacy incident fields were accepted: {payload}")


def test_http_incident_canonical_payload_shapes_are_accepted():
    payloads = [
        {"action": "decision", "fingerprint": FINGERPRINT, "state_revision": "rev-7"},
        {
            "action": "record", "operation_class": "command", "message": "failed",
            "root_cause": "cause", "verified_fix": "fix", "exit_code": 1,
            "state_revision": "rev-7", "evidence_ids": ["ev-1"], "affected_paths": ["src/a.py"],
        },
        {"action": "find", "query": "timeout", "limit": 25},
    ]
    for payload in payloads:
        payload.update(root=".", tenant="tenant-x")
        http_server.Handler._validate_payload("/api/agent-state/incidents", payload)


def test_http_incident_accepts_windows_access_violation_exit_codes():
    for exit_code in (3221225477, -1073741819):
        http_server.Handler._validate_payload("/api/agent-state/incidents", {
            "action": "record", "operation_class": "command", "exit_code": exit_code,
            "root": ".", "tenant": "tenant-x",
        })


def test_http_incident_fields_reject_coercion_and_unbounded_find():
    invalid_payloads = [
        {"action": "decision", "fingerprint": {**FINGERPRINT, "error_class": 12}},
        {"action": "record", "exit_code": "1"},
        {"action": "record", "exit_code": True},
        {"action": "record", "evidence_ids": "evidence-1"},
        {"action": "find", "query": "timeout", "limit": True},
        {"action": "find", "query": "timeout", "limit": 101},
    ]
    for payload in invalid_payloads:
        payload.update(root=".", tenant="tenant-x")
        try:
            http_server.Handler._validate_payload("/api/agent-state/incidents", payload)
        except http_server.RequestBodyError:
            continue
        raise AssertionError(f"invalid incident payload was accepted: {payload}")


def test_mcp_incident_actions_send_canonical_scoped_payloads(monkeypatch, tmp_path):
    _activate_coord(monkeypatch)
    client = _FakeClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    implementation = _implementation()

    implementation(
        action="negative_knowledge_record", root=str(tmp_path), tenant="tenant-x",
        record={"operation_class": "command", "message": "failed", "exit_code": 1},
    )
    implementation(
        action="negative_knowledge_find", root=str(tmp_path), tenant="tenant-x",
        query="timeout", limit=25,
    )
    implementation(
        action="negative_knowledge_find", root=str(tmp_path), tenant="tenant-x",
        query="default limit",
    )
    implementation(
        action="incident_decision", root=str(tmp_path), tenant="tenant-x",
        fingerprint=FINGERPRINT, state_revision="rev-7",
    )

    assert client.calls == [
        ("post", "/api/agent-state/incidents", {
            "operation_class": "command", "message": "failed", "exit_code": 1,
            "action": "record", "root": str(tmp_path), "tenant": "tenant-x",
        }),
        ("post", "/api/agent-state/incidents", {
            "action": "find", "root": str(tmp_path), "tenant": "tenant-x",
            "query": "timeout", "limit": 25,
        }),
        ("post", "/api/agent-state/incidents", {
            "action": "find", "root": str(tmp_path), "tenant": "tenant-x",
            "query": "default limit", "limit": 100,
        }),
        ("coord", {
            "action": "incident_decision", "fingerprint": FINGERPRINT,
            "state_revision": "rev-7", "root": str(tmp_path), "tenant": "tenant-x",
        }),
    ]


def test_find_limit_schema_is_action_scoped():
    schema = operation_parameters_schema("local_ai_coord")
    condition = next(
        item for item in schema["allOf"]
        if item.get("if", {}).get("properties", {}).get("action", {}).get("const") == "negative_knowledge_find"
    )
    assert condition["then"]["properties"]["limit"] == {
        "type": "integer", "minimum": 1, "maximum": 100, "default": 100,
    }


def test_mcp_incident_decision_rejects_ignored_outcome_alias(monkeypatch, tmp_path):
    _activate_coord(monkeypatch)
    client = _FakeClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)

    result = _implementation()(
        action="incident_decision", root=str(tmp_path), tenant="tenant-x",
        fingerprint=FINGERPRINT, state_revision="rev-7",
        tool_outcome={"error": "ignored legacy field"},
    )

    assert result["success"] is False
    assert client.calls == []


def test_mcp_negative_knowledge_rejects_legacy_fields(monkeypatch, tmp_path):
    _activate_coord(monkeypatch)
    client = _FakeClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)

    record_result = _implementation()(
        action="negative_knowledge_record", root=str(tmp_path), tenant="tenant-x",
        record={"operation_class": "command", "message": "failed"}, reason="legacy",
    )
    find_result = _implementation()(
        action="negative_knowledge_find", root=str(tmp_path), tenant="tenant-x",
        query="timeout", limit=10, key="legacy",
    )

    assert record_result["success"] is False
    assert find_result["success"] is False
    assert client.calls == []


def test_sdk_coord_forwards_canonical_incident_scope_and_revision():
    client = object.__new__(HubClient)
    calls = []
    client.post = lambda path, payload: calls.append((path, payload)) or {"success": True}

    HubClient.coord(
        client, action="incident_decision", fingerprint=FINGERPRINT,
        state_revision="rev-7", root="C:/repo", tenant="tenant-x",
    )

    assert calls == [(
        "/api/agent-state/incidents", {
            "action": "decision", "fingerprint": FINGERPRINT,
            "state_revision": "rev-7", "root": "C:/repo", "tenant": "tenant-x",
        },
    )]


def test_sdk_coord_keeps_record_scope_outside_record_object():
    client = object.__new__(HubClient)
    calls = []
    client.post = lambda path, payload: calls.append((path, payload)) or {"success": True}

    HubClient.coord(
        client, action="negative_knowledge_record",
        record={"operation_class": "command", "message": "failed"},
        root="C:/repo", tenant="tenant-x",
    )
    HubClient.coord(
        client, action="negative_knowledge_find", query="timeout", limit=25,
        root="C:/repo", tenant="tenant-x",
    )

    assert calls == [
        ("/api/agent-state/incidents", {
            "operation_class": "command", "message": "failed", "root": "C:/repo",
            "tenant": "tenant-x", "action": "record",
        }),
        ("/api/agent-state/incidents", {
            "action": "find", "query": "timeout", "limit": 25,
            "root": "C:/repo", "tenant": "tenant-x",
        }),
    ]


def test_sdk_incident_actions_reject_ignored_aliases_before_dispatch():
    client = object.__new__(HubClient)
    calls = []
    client.post = lambda path, payload: calls.append((path, payload)) or {"success": True}

    invalid = [
        {"action": "incident_decision", "fingerprint": FINGERPRINT, "state_revision": "r1", "revision": "old"},
        {"action": "negative_knowledge_find", "query": "timeout", "key": "old"},
        {"action": "negative_knowledge_record", "record": {"message": "x", "reason": "old"}},
    ]
    for arguments in invalid:
        result = HubClient.coord(client, **arguments)
        assert result["success"] is False
        assert result["status_code"] == 400
    assert calls == []


def test_incident_record_constraints_are_action_scoped_and_windows_bounded():
    schema = operation_parameters_schema("local_ai_coord")
    assert schema["properties"]["record"] == {"type": "object"}
    record_condition = next(
        item for item in schema["allOf"]
        if item.get("if", {}).get("properties", {}).get("action", {}).get("const") == "negative_knowledge_record"
    )
    assert record_condition["then"]["properties"]["record"]["properties"]["exit_code"] == {
        "type": "integer", "minimum": -(1 << 31), "maximum": (1 << 32) - 1,
    }
    for exit_code in (3221225477, -1073741819):
        assert validate_operation_arguments("local_ai_coord", "negative_knowledge_record", {
            "record": {"message": "failure", "exit_code": exit_code},
        }) is None
    assert validate_operation_arguments("local_ai_coord", "negative_knowledge_record", {
        "record": {"message": "failure", "exit_code": True},
    }) is not None


def test_global_coord_record_schema_does_not_restrict_other_action_objects():
    properties = operation_parameters_schema("local_ai_coord")["properties"]
    assert properties["record"] == {"type": "object"}
