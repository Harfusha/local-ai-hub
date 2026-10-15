"""Deferred boundary coverage for canonical task event synchronization inputs."""
from __future__ import annotations

import asyncio

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.operation_contracts import operation_input_schema, validate_operation_arguments


def _activate_coord(monkeypatch):
    from local_ai_hub.operational_mode import OperationalModeSnapshot

    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server.FEATURES, "agent_os", True)
    snapshot = OperationalModeSnapshot("active", 1, None)
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _state_dir: snapshot)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_kwargs: None)
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *_args, **_kwargs: None)


class _FakeClient:
    def __init__(self):
        self.calls = []

    def post(self, path, payload, **kwargs):
        self.calls.append((path, payload))
        return {"success": True, "count": len(payload.get("events", []))}


@pytest.mark.parametrize(("arguments", "expected"), [
    (
        {"sync_action": "export", "stream_id": "task:t-1", "after_seq": 0, "limit": 12},
        {"action": "export", "stream_id": "task:t-1", "after_seq": 0, "limit": 12},
    ),
    (
        {},
        {"action": "export", "stream_id": "", "after_seq": 0, "limit": 1000},
    ),
])
def test_registered_task_sync_export_uses_canonical_payload(monkeypatch, arguments, expected):
    _activate_coord(monkeypatch)
    client = _FakeClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)

    asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
        "action": "task_sync", **arguments,
    }))

    assert client.calls == [("/api/agent-state/events/delta", expected)]


def test_registered_task_sync_import_forwards_events(monkeypatch):
    _activate_coord(monkeypatch)
    client = _FakeClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    events = [{"event_id": "event-1", "kind": "task.created"}]

    asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
        "action": "task_sync", "sync_action": "import", "events": events,
    }))

    assert client.calls == [("/api/agent-state/events/delta", {"action": "import", "events": events})]


@pytest.mark.parametrize("sync_action", [" EXPORT", "Export", "import ", "merge"])
def test_task_sync_selector_is_not_normalized(monkeypatch, sync_action):
    _activate_coord(monkeypatch)
    client = _FakeClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)

    result = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
        "action": "task_sync", "sync_action": sync_action,
    }))

    assert client.calls == []
    assert "400" in str(result)


@pytest.mark.parametrize(("field", "value"), [
    ("status", ""), ("key", ""), ("task_id", ""), ("ttl_seconds", 0),
    ("max_tokens", 0), ("record", {}),
])
def test_shared_contract_rejects_retired_task_sync_aliases(field, value):
    assert validate_operation_arguments("local_ai_coord", "task_sync", {field: value}) is not None


@pytest.mark.parametrize(("arguments",), [
    ({"sync_action": "import"},),
    ({"sync_action": "import", "events": [], "stream_id": "task:t-1"},),
    ({"sync_action": "import", "events": [], "after_seq": 0},),
    ({"sync_action": "import", "events": [], "limit": 100},),
    ({"sync_action": "export", "events": []},),
])
def test_shared_contract_rejects_irrelevant_or_missing_sync_fields(arguments):
    assert validate_operation_arguments("local_ai_coord", "task_sync", arguments) is not None


def test_task_sync_fields_are_action_scoped():
    schema = operation_input_schema("local_ai_coord", "task_sync")
    assert {"sync_action", "stream_id", "after_seq", "limit", "events"} <= set(schema["properties"])
    assert "limit" not in operation_input_schema("local_ai_coord", "task_get")["properties"]
    assert validate_operation_arguments("local_ai_coord", "task_get", {"sync_action": "export"}) is not None
