import asyncio
import json
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.operational_mode import OperationalModeSnapshot


def test_registered_memory_find_forwards_key_and_status(monkeypatch, tmp_path):
    requests = []

    class Client:
        def coord(self, **kwargs):
            requests.append(kwargs)
            return {"success": True, "records": []}

    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server.FEATURES, "agent_os", True)
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _state_dir: OperationalModeSnapshot("active", 1, None))
    monkeypatch.setattr(mcp_server, "CLIENT", Client())
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_: None)
    asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
        "action": "memory_find", "root": str(tmp_path), "scope": "repository",
        "query": "needle", "key": "exact-key", "status": "active", "limit": 5,
    }))
    assert len(requests) == 1
    assert requests[0]["query"] == "needle"
    assert requests[0]["key"] == "exact-key"
    assert requests[0]["status"] == "active"
    assert requests[0]["limit"] == 5


def test_registered_memory_record_forwards_explicit_status(monkeypatch, tmp_path):
    requests = []

    class Client:
        def coord(self, **kwargs):
            requests.append(kwargs)
            return {"success": True, "record": {"record_id": "synthetic"}}

    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server.FEATURES, "agent_os", True)
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _state_dir: OperationalModeSnapshot("active", 1, None))
    monkeypatch.setattr(mcp_server, "CLIENT", Client())
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_: None)
    asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
        "action": "memory_record", "root": str(tmp_path), "scope": "repository",
        "key": "candidate-key", "value": "synthetic", "status": "candidate",
    }))
    assert len(requests) == 1
    assert requests[0]["status"] == "candidate"


@pytest.mark.parametrize("key,status,expected", [
    ("alpha", "active", ["alpha"]),
    ("beta", "candidate", ["beta"]),
    ("absent", "active", []),
    ("beta", "active", []),
])
def test_registered_memory_find_filters_real_store(monkeypatch, tmp_path, key, status, expected):
    from local_ai_hub import http_server
    from local_ai_hub.agent_events import AgentStateStore
    from local_ai_hub.agent_identity import AgentScope
    from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStatus, MemoryStore
    from local_ai_hub.client import HubClient

    root = str(tmp_path.resolve())
    repository_id = "synthetic-repository-id"
    store = MemoryStore(AgentStateStore(tmp_path / "memory.sqlite3"))
    for record_key, record_status in (("alpha", MemoryStatus.ACTIVE), ("beta", MemoryStatus.CANDIDATE)):
        record = MemoryRecord.create(
            kind=MemoryKind.FACT, scope=AgentScope.REPOSITORY, key=record_key,
            value="shared synthetic text", status=record_status,
            provenance={"root": root, "repository_id": repository_id},
        )
        store.record(record, actor="user", idempotency_key=f"record-{record_key}")

    def post(path, payload, **_kwargs):
        payload = json.loads(json.dumps(payload))
        assert path == "/api/agent-state/memory"
        http_server.Handler._validate_payload(path, payload)
        assert payload["action"] == "find" and payload["root"] == root
        records = store.find(
            scope=AgentScope.REPOSITORY, root=root, repository_id=repository_id,
            key=payload.get("key"), query=payload.get("query"),
            status=MemoryStatus(payload["status"]) if payload.get("status") else None,
            limit=payload["limit"],
        )
        return {"success": True, "records": [record.to_dict() for record in records]}

    client = object.__new__(HubClient)
    client.post = post
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server.FEATURES, "agent_os", True)
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _state_dir: OperationalModeSnapshot("active", 1, None))
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_: None)
    result = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
        "action": "memory_find", "root": root, "scope": "repository", "query": "shared synthetic",
        "key": key, "status": status, "limit": 10,
    }))
    contents = result[0] if isinstance(result, tuple) else result
    visible = json.loads(next(item.text for item in contents if item.type == "text"))
    assert visible["success"] is True
    assert [record["key"] for record in visible.get("records", [])] == expected


def test_memory_filters_over_isolated_loopback_http(monkeypatch, tmp_path):
    from local_ai_hub import http_server
    from local_ai_hub.agent_events import AgentStateStore
    from local_ai_hub.agent_identity import AgentScope
    from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStatus, MemoryStore
    from local_ai_hub.client import HubClient
    from local_ai_hub.project_config import resolve_project_context

    root = str(tmp_path.resolve())
    repository_id = resolve_project_context(root, tmp_path).coordination_id
    state = AgentStateStore(tmp_path / "memory-http.sqlite3")
    store = MemoryStore(state)
    for key, status in (("alpha", MemoryStatus.ACTIVE), ("beta", MemoryStatus.CANDIDATE)):
        store.record(MemoryRecord.create(
            kind=MemoryKind.FACT, scope=AgentScope.REPOSITORY, key=key,
            value="shared synthetic text", status=status,
            provenance={"root": root, "repository_id": repository_id},
        ), actor="user", idempotency_key=f"http-{key}")
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"server": {}, "observability": {}}, agent_memory=store, agent_state=state))
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args: None)
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)
    monkeypatch.setattr(http_server.Handler, "_begin_trace", lambda self, _path: None)
    monkeypatch.setattr(http_server.Handler, "_finish_debug_trace", lambda self, *_args, **_kwargs: None)
    monkeypatch.setattr(http_server.Handler, "_memory_project_identity", lambda self, supplied: (root, repository_id) if supplied == root else None)
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server.FEATURES, "agent_os", True)
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _state_dir: OperationalModeSnapshot("active", 1, None))
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_: None)
    server = ThreadingHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = HubClient(auto_start=False)
        client._http_host, client._http_port = server.server_address
        client.base_url = f"http://127.0.0.1:{server.server_port}"
        monkeypatch.setattr(mcp_server, "CLIENT", client)
        created = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
            "action": "memory_record", "root": root, "scope": "repository",
            "key": "gamma", "value": "shared synthetic text", "status": "candidate",
        }))
        created_contents = created[0] if isinstance(created, tuple) else created
        created_response = json.loads(next(item.text for item in created_contents if item.type == "text"))
        assert created_response["success"] is True, created_response
        assert created_response["record"]["status"] == "candidate"
        for key, status, expected in (("alpha", "active", ["alpha"]),
                                      ("beta", "candidate", ["beta"]),
                                      ("gamma", "candidate", ["gamma"]),
                                      ("absent", "active", []), ("beta", "active", [])):
            result = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
                "action": "memory_find", "root": root, "scope": "repository", "query": "shared synthetic",
                "key": key, "status": status, "limit": 10,
            }))
            contents = result[0] if isinstance(result, tuple) else result
            response = json.loads(next(item.text for item in contents if item.type == "text"))
            assert response["success"] is True
            assert [record["key"] for record in response.get("records", [])] == expected
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()
