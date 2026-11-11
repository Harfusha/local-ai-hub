from __future__ import annotations

import sqlite3
import asyncio
import json
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
import pytest

from local_ai_hub.agent_events import AgentEvent, AgentStateStore, AppendResult, SwarmPubSub


@pytest.mark.parametrize("message", [None, False, 0, "", [], {}, "hello", [0], {"nested": False}])
@pytest.mark.parametrize("durable", [False, True])
def test_pubsub_roundtrips_falsey_json_values(tmp_path, message, durable):
    state = AgentStateStore(tmp_path / "pubsub.sqlite3") if durable else None
    bus = SwarmPubSub(state_store=state)
    published = bus.publish("falsey", message, sender="synthetic")
    assert published["success"] is True
    polled = bus.poll("falsey", after_seq=0)
    assert polled["success"] is True
    assert len(polled["messages"]) == 1
    assert polled["messages"][0]["payload"] == message
    assert type(polled["messages"][0]["payload"]) is type(message)


@pytest.mark.parametrize("message", [float("nan"), float("inf"), {"bad": {1, 2}}])
def test_pubsub_rejects_non_json_without_recording_message(tmp_path, message):
    bus = SwarmPubSub(state_store=AgentStateStore(tmp_path / "pubsub-invalid.sqlite3"))
    result = bus.publish("invalid", message, sender="synthetic")
    assert result["success"] is False
    assert bus.poll("invalid", after_seq=0)["messages"] == []


@pytest.mark.parametrize("durable", [False, True])
def test_pubsub_poll_since_timestamp_filters_old_messages(tmp_path, durable):
    state = AgentStateStore(tmp_path / "pubsub-timestamp.sqlite3") if durable else None
    bus = SwarmPubSub(state_store=state)
    assert bus.publish("timestamp", "old")["success"] is True
    first_timestamp = bus.poll("timestamp", after_seq=0)["messages"][0]["timestamp"]
    time.sleep(0.002)
    assert bus.publish("timestamp", "new")["success"] is True

    result = bus.poll("timestamp", since_timestamp=first_timestamp, after_seq=0)

    assert [message["payload"] for message in result["messages"]] == ["new"]


def test_pubsub_diagnostic_projection_preserves_only_caller_payload():
    from local_ai_hub.agent_diagnostics import project_agent_response, project_pubsub_poll_response

    payload = {"prompt": "caller", "debug": "caller", "_token_accounting": {"custom": 1}}
    source = {"success": True, "debug": "private envelope", "messages": [{
        "debug": "private event", "payload": payload,
    }]}
    projected = project_pubsub_poll_response(source, enabled=False)
    assert "debug" not in projected
    assert "debug" not in projected["messages"][0]
    assert projected["messages"][0]["payload"] == payload
    ordinary = project_agent_response(source, enabled=False)
    assert ordinary["messages"][0]["payload"] == {}


@pytest.mark.parametrize("message", [None, False, 0, "", [], {}, "hello", [0], {"nested": False}])
def test_registered_mcp_pubsub_preserves_falsey_json(tmp_path, monkeypatch, message):
    from local_ai_hub import http_server, mcp_server
    from local_ai_hub.client import HubClient
    from local_ai_hub.operational_mode import OperationalModeSnapshot
    from local_ai_hub.services import LocalAIServices

    bus = SwarmPubSub(state_store=AgentStateStore(tmp_path / "pubsub-mcp.sqlite3"))
    service = object.__new__(LocalAIServices)
    service.agent_state = bus.state_store
    monkeypatch.setattr(SwarmPubSub, "get_default", classmethod(lambda cls, state_store=None: bus))

    def post(path, payload, **_kwargs):
        payload = json.loads(json.dumps(payload))
        http_server.Handler._validate_payload(path, payload)
        if path == "/api/coord/pubsub_publish":
            return service.pubsub_publish(payload["topic"], payload["message"], sender=payload["publisher"])
        assert path == "/api/coord/pubsub_poll"
        return service.pubsub_poll(payload["topic"], after_seq=payload["after_seq"], limit=payload["limit"])

    client = object.__new__(HubClient)
    client.post = post

    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server.FEATURES, "agent_os", True)
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _state_dir: OperationalModeSnapshot("active", 1, None))
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_: None)

    def call(action, **kwargs):
        result = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
            "action": action, "root": str(tmp_path), "topic": "falsey-mcp", **kwargs,
        }))
        contents = result[0] if isinstance(result, tuple) else result
        return json.loads(next(item.text for item in contents if item.type == "text"))

    assert call("pubsub_publish", message=message, publisher="synthetic")["success"] is True
    received = call("pubsub_poll", after_seq=0, limit=10)
    assert received["success"] is True
    actual = received["messages"][0]["payload"]
    assert type(actual) is type(message) and actual == message


def test_registered_mcp_pubsub_rejects_incomplete_payload_at_small_budget(tmp_path, monkeypatch):
    from local_ai_hub import mcp_server
    from local_ai_hub.operational_mode import OperationalModeSnapshot

    bus = SwarmPubSub(state_store=AgentStateStore(tmp_path / "pubsub-budget.sqlite3"))
    assert bus.publish("large-mcp", {"text": "x" * 10000})["success"] is True

    class StoreTransport:
        def coord(self, **kwargs):
            return bus.poll(kwargs["topic"], after_seq=kwargs["after_seq"], limit=kwargs["limit"])

    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server.FEATURES, "agent_os", True)
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _state_dir: OperationalModeSnapshot("active", 1, None))
    monkeypatch.setattr(mcp_server, "CLIENT", StoreTransport())
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_: None)
    monkeypatch.setattr(mcp_server, "RESPONSE_BUDGET_ENABLED", True)
    result = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
        "action": "pubsub_poll", "root": str(tmp_path), "topic": "large-mcp",
        "after_seq": 0, "limit": 10, "max_response_tokens": 512,
    }))
    contents = result[0] if isinstance(result, tuple) else result
    response = json.loads(next(item.text for item in contents if item.type == "text"))
    assert response["success"] is False
    assert response.get("error")


@pytest.mark.parametrize("budget", [512, 1024, 2048, 4096])
def test_registered_mcp_pubsub_never_succeeds_with_changed_payload(tmp_path, monkeypatch, budget):
    from local_ai_hub import mcp_server
    from local_ai_hub.operational_mode import OperationalModeSnapshot

    message = {"text": "payload-" * 300, "empty": [], "enabled": False}
    bus = SwarmPubSub(state_store=AgentStateStore(tmp_path / "pubsub-budget-boundary.sqlite3"))
    assert bus.publish("budget-boundary", message)["success"] is True

    class StoreTransport:
        def coord(self, **kwargs):
            return bus.poll(kwargs["topic"], after_seq=kwargs["after_seq"], limit=kwargs["limit"])

    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server.FEATURES, "agent_os", True)
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _state_dir: OperationalModeSnapshot("active", 1, None))
    monkeypatch.setattr(mcp_server, "CLIENT", StoreTransport())
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_: None)
    monkeypatch.setattr(mcp_server, "RESPONSE_BUDGET_ENABLED", True)
    result = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
        "action": "pubsub_poll", "root": str(tmp_path), "topic": "budget-boundary",
        "after_seq": 0, "limit": 10, "max_response_tokens": budget,
    }))
    contents = result[0] if isinstance(result, tuple) else result
    visible = json.loads(next(item.text for item in contents if item.type == "text"))
    structured = result[1] if isinstance(result, tuple) else visible
    for response in (visible, structured):
        if response["success"] is True:
            assert response["messages"][0]["payload"] == message
        else:
            assert response.get("error")


@pytest.mark.parametrize("message", [None, False, 0, "", [], {}, "hello", [0], {"nested": False},
    {"prompt": "caller text", "debug": "caller value", "returned_count": 1, "matches_count": 1}])
def test_pubsub_roundtrip_over_isolated_loopback_http(tmp_path, monkeypatch, message):
    from local_ai_hub import http_server, mcp_server
    from local_ai_hub.client import HubClient
    from local_ai_hub.operational_mode import OperationalModeSnapshot
    from local_ai_hub.services import LocalAIServices

    state = AgentStateStore(tmp_path / "http-pubsub.sqlite3")
    bus = SwarmPubSub(state_store=state)
    service = object.__new__(LocalAIServices)
    service.agent_state = state
    monkeypatch.setattr(SwarmPubSub, "get_default", classmethod(lambda cls, state_store=None: bus))
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"server": {}, "observability": {}}, services=service))
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args: None)
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)
    monkeypatch.setattr(http_server.Handler, "_begin_trace", lambda self, _path: None)
    monkeypatch.setattr(http_server.Handler, "_finish_debug_trace", lambda self, *_args, **_kwargs: None)
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server.FEATURES, "agent_os", True)
    monkeypatch.setattr(mcp_server, "CFG", {"debug_traces": {"enabled": False}})
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

        def call(action, **kwargs):
            result = asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", {
                "action": action, "root": str(tmp_path), "topic": "http-loopback", **kwargs,
            }))
            contents = result[0] if isinstance(result, tuple) else result
            return json.loads(next(item.text for item in contents if item.type == "text"))

        assert call("pubsub_publish", message=message, publisher="synthetic")["success"] is True
        result = call("pubsub_poll", after_seq=0, limit=10)
        assert result["success"] is True
        received = result["messages"][0]["payload"]
        assert type(received) is type(message) and received == message
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()

def test_generated_event_identifiers_use_full_uuid_entropy_and_keep_supplied_keys():
    created = AgentEvent.create("stream-1", "test.event")
    restored = AgentEvent.from_dict(created.to_dict())

    for value, prefix in (
        (created.event_id, "evt_"),
        (created.idempotency_key, "idemp_"),
        (restored.event_id, "evt_"),
        (restored.idempotency_key, "idemp_"),
    ):
        assert value.startswith(prefix)
        suffix = value[len(prefix):]
        assert len(suffix) == 32
        assert int(suffix, 16) >= 0

    caller_key = AgentEvent.create("stream-1", "test.event", idempotency_key="client-key")
    assert caller_key.idempotency_key == "client-key"

    restored_key = AgentEvent.from_dict(
        {**created.to_dict(), "idempotency_key": "stored-key"}
    )
    assert restored_key.idempotency_key == "stored-key"


def test_from_dict_rejects_missing_required_event_fields():
    canonical = AgentEvent.create("stream-1", "test.event").to_dict()
    for field in canonical:
        incomplete = {key: value for key, value in canonical.items() if key != field}
        with pytest.raises(KeyError, match=field):
            AgentEvent.from_dict(incomplete)


def test_from_dict_preserves_explicit_empty_optional_event_fields():
    canonical = AgentEvent.create("stream-1", "test.event").to_dict()

    restored = AgentEvent.from_dict(canonical)

    assert restored.correlation_id == ""
    assert restored.seq is None


def test_from_dict_rejects_noncanonical_fields():
    canonical = AgentEvent.create("stream-1", "test.event").to_dict()
    with pytest.raises(ValueError, match="unexpected AgentEvent fields"):
        AgentEvent.from_dict({**canonical, "task_name": "legacy-alias"})


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("event_id", "", ValueError),
        ("stream_id", "stream\x00id", ValueError),
        ("kind", 7, ValueError),
        ("payload", [], TypeError),
        ("idempotency_key", None, ValueError),
        ("correlation_id", "corr\x00id", ValueError),
        ("actor", "  ", ValueError),
        ("created_at", True, ValueError),
        ("created_at", float("nan"), ValueError),
        ("seq", True, ValueError),
        ("seq", 1.5, ValueError),
        ("seq", -1, ValueError),
    ],
)
def test_from_dict_rejects_invalid_canonical_value_formats(field, value, error):
    canonical = AgentEvent.create("stream-1", "test.event").to_dict()

    with pytest.raises(error):
        AgentEvent.from_dict({**canonical, field: value})


def test_schema_drift_fails_closed_without_deleting_durable_database(tmp_path: Path):
    db_path = tmp_path / "agent_state.sqlite3"
    con = sqlite3.connect(db_path)
    try:
        con.execute("""
            CREATE TABLE agent_events (
                stream_id TEXT NOT NULL, seq INTEGER NOT NULL, event_id TEXT NOT NULL,
                kind TEXT NOT NULL, payload TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                correlation_id TEXT NOT NULL, actor TEXT NOT NULL, created_at REAL NOT NULL,
                future_field TEXT, PRIMARY KEY (stream_id, seq), UNIQUE (stream_id, idempotency_key)
            )
        """)
        con.execute(
            "INSERT INTO agent_events VALUES ('task-1',1,'event-1','task.created','{}','key-1','','test',1.0,NULL)"
        )
        con.execute("CREATE TABLE durable_sentinel (value TEXT NOT NULL)")
        con.execute("INSERT INTO durable_sentinel (value) VALUES ('preserve')")
        con.commit()
    finally:
        con.close()
    original_bytes = db_path.read_bytes()

    with pytest.raises(RuntimeError, match="schema mismatch"):
        AgentStateStore(db_path)._ensure_schema()

    assert db_path.read_bytes() == original_bytes
    con = sqlite3.connect(db_path)
    try:
        assert con.execute("SELECT value FROM durable_sentinel").fetchone() == ("preserve",)
        assert con.execute("SELECT event_id FROM agent_events").fetchone() == ("event-1",)
    finally:
        con.close()


def test_append_returns_existing_sequence_for_same_idempotency_key(tmp_path: Path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    event = AgentEvent.create("task-1", "task.created", {"title": "index"}, "key-1")
    first = store.append(event)
    assert first.seq == 1
    assert first.duplicate is False
    second = store.append(event)
    assert second.seq == 1
    assert second.duplicate is True
    assert store.events("task-1") == [event.with_seq(1)]


def test_events_are_ordered_per_stream(tmp_path: Path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store.append(AgentEvent.create("task-1", "task.created", {}, "one"))
    store.append(AgentEvent.create("task-1", "task.planned", {}, "two"))
    assert [event.seq for event in store.events("task-1")] == [1, 2]


def test_events_stream_isolation_and_after_seq(tmp_path: Path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store.append(AgentEvent.create("task-1", "task.created", {"step": 1}, "k1"))
    store.append(AgentEvent.create("task-2", "task.created", {"step": 1}, "k2"))
    store.append(AgentEvent.create("task-1", "task.updated", {"step": 2}, "k3"))

    evs1 = store.events("task-1")
    assert len(evs1) == 2
    assert [e.seq for e in evs1] == [1, 2]

    evs2 = store.events("task-2")
    assert len(evs2) == 1
    assert evs2[0].seq == 1

    after = store.events("task-1", after_seq=1)
    assert len(after) == 1
    assert after[0].seq == 2


def test_snapshot_and_restore(tmp_path: Path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store.append(AgentEvent.create("task-1", "task.created", {"val": 10}, "k1"))
    snap_id = store.snapshot("task-1", {"status": "active", "val": 10}, seq=1)
    assert snap_id > 0
    latest = store.latest_snapshot("task-1")
    assert latest is not None
    assert latest["state"]["val"] == 10
    assert latest["seq"] == 1


def test_payload_size_limit(tmp_path: Path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3", max_payload_bytes=100)
    large_payload = {"data": "x" * 200}
    event = AgentEvent.create("task-1", "task.large", large_payload, "k-large")
    with pytest.raises(ValueError, match="payload exceeds"):
        store.append(event)


def test_subscribe_and_publish_events(tmp_path: Path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    q = store.subscribe()
    ev1 = AgentEvent.create("task-1", "task.created", {"step": 1}, "k1")
    store.append(ev1)
    received = q.get_nowait()
    assert received.kind == "task.created"
    assert received.seq == 1
    assert received.stream_id == "task-1"

    # Unsubscribe
    store.unsubscribe(q)
    ev2 = AgentEvent.create("task-1", "task.step", {"step": 2}, "k2")
    store.append(ev2)
    assert q.empty()
