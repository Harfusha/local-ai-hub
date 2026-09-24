from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from types import SimpleNamespace

from local_ai_hub import http_server
from local_ai_hub.debug_traces import DebugTraceStore
from local_ai_hub.telemetry import TelemetryStore


def test_telemetry_timeline_is_recent_and_cursor_pages_older_rows(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.01)
    try:
        for index in range(5):
            store.record_http(action=f"/api/operation/{index}", success=True)
        assert store.flush(1)

        recent = store.get_timeline_page(limit=2)
        older = store.get_timeline_page(limit=2, before_id=recent["next_cursor"])

        assert [row["action"] for row in recent["timeline"]] == ["/api/operation/3", "/api/operation/4"]
        assert recent["has_more"] is True
        assert [row["action"] for row in older["timeline"]] == ["/api/operation/1", "/api/operation/2"]
    finally:
        store.close()


def test_telemetry_query_window_clamps_unbounded_days(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.01)
    try:
        before = time.time()
        cutoff = store._cutoff(10**9)
        assert before - cutoff <= 3650 * 86400 + 1
    finally:
        store.close()


def test_trace_detail_is_paginated_and_response_bytes_are_capped(tmp_path):
    store = DebugTraceStore({
        "server": {"state_dir": str(tmp_path)},
        "debug_traces": {"max_event_bytes": 8192, "max_detail_response_bytes": 16384},
    })
    trace_id = store.start(kind="api_request", tenant="test")
    for index in range(6):
        store.event(trace_id, "output_delta", {"text": f"{index}:" + "x" * 2500})

    first = store.detail(trace_id, since_seq=0, limit=2)
    second = store.detail(trace_id, since_seq=first["next_seq"], limit=2)

    assert len(first["events"]) == 2
    assert first["has_more"] is True
    assert second["events"][0]["seq"] > first["events"][-1]["seq"]
    assert first["response_bytes"] <= store.max_detail_response_bytes


def test_db_query_enforces_row_and_byte_budgets(monkeypatch, tmp_path):
    db = tmp_path / "agent_state.sqlite3"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE payloads (payload TEXT)")
        con.executemany("INSERT INTO payloads VALUES (?)", [("x" * 3000,) for _ in range(4)])
        con.commit()
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"server": {"state_dir": str(tmp_path)}}))
    monkeypatch.setattr(http_server, "_DB_QUERY_MAX_RESPONSE_BYTES", 8192)

    result = http_server.Handler._handle_db_query(None, "agent_state", "SELECT payload FROM payloads")

    assert result["success"] is True
    assert result["truncated"] is True
    assert result["response_bytes"] <= 8192
    assert len(result["rows"]) < 4


def test_db_query_deadline_reports_degraded_timeout(monkeypatch, tmp_path):
    db = tmp_path / "agent_state.sqlite3"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE marker (value INTEGER)")
        con.execute("INSERT INTO marker VALUES (1)")
        con.commit()
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"server": {"state_dir": str(tmp_path)}}))
    monkeypatch.setattr(http_server, "_DB_QUERY_TIMEOUT_SECONDS", 0.001)

    result = http_server.Handler._handle_db_query(
        None,
        "agent_state",
        "WITH RECURSIVE counter(value) AS (VALUES(0) UNION ALL SELECT value + 1 FROM counter WHERE value < 100000000) SELECT sum(value) FROM counter",
    )

    assert result["success"] is False
    assert result["degraded"] is True
    assert result["retryable"] is True
    assert result["error"] == "query time budget exceeded"


def test_admin_action_policy_rejects_wrong_method_and_audits_metadata_only(monkeypatch):
    handler = object.__new__(http_server.Handler)
    handler.command = "GET"
    handler.path = "/api/maintenance/optimize_db"
    handler._authorization_succeeded = True
    sent = []
    handler._send = lambda status, body: sent.append((status, body))

    assert handler._authorize_admin_action("maintenance.optimize_db") is False
    assert sent[0][0] == 405

    audits = []
    telemetry = SimpleNamespace(record_system=lambda action, **event: audits.append((action, event)))
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(telemetry=telemetry))
    handler._admin_operation = "maintenance.optimize_db"
    handler._request_started = time.perf_counter() - 0.01
    handler._audit_admin_action(200, {"prompt": "secret", "source_text": "private", "path": "C:\\private\\repo"})

    assert audits[0][0] == "admin.maintenance.optimize_db"
    assert "prompt" not in audits[0][1]
    assert "source_text" not in audits[0][1]
    assert "path" not in audits[0][1]


def test_admin_action_requires_exact_route_and_payload_action():
    handler = object.__new__(http_server.Handler)
    handler.command = "POST"
    handler.path = "/api/control"
    handler._authorization_succeeded = True
    handler._admin_payload = {"action": "restart_hub"}
    sent = []
    handler._send = lambda status, body: sent.append((status, body))

    assert handler._authorize_admin_action("control.stop_service") is False
    assert sent[-1][0] == 403
    handler._admin_payload = {"action": "stop_service"}
    assert handler._authorize_admin_action("control.stop_service") is True
    assert handler._admin_operation == "control.stop_service"


def test_status_action_aliases_match_live_and_generated_schemas(monkeypatch):
    from local_ai_hub import mcp_server
    from local_ai_hub.generator import generate_mcp_tool_schemas

    details = {"brief", "cache", "telemetry", "full", "agent_state"}
    aliases = {"status", "health", "check", "info"}
    schemas = generate_mcp_tool_schemas({})["local_ai_status"]["parameters"]["properties"]
    live = mcp_server.mcp._tool_manager._tools["local_ai_status"].parameters["properties"]

    assert set(live["detail"]["enum"]) == details
    assert set(schemas["detail"]["enum"]) == details
    assert set(live["action"]["enum"]) == set(schemas["action"]["enum"])
    assert (details | aliases) <= set(live["action"]["enum"])

    calls = []
    status = {"hub_online": True, "version": "test", "scheduler": {}, "observability": {}, "runtime_stats": {}}

    class Client:
        def get(self, path):
            calls.append(path)
            return status

        def status(self, **kwargs):
            calls.append(("status", kwargs))
            return status

    monkeypatch.setattr(mcp_server, "CLIENT", Client())
    monkeypatch.setattr(mcp_server, "FEATURES", SimpleNamespace(status=True, tasks=False, has_any_model=lambda: False))
    expected_calls = {
        **{alias: ["/api/live/status?light=1&scope=process"] for alias in aliases},
        "brief": ["/api/live/status?light=1&scope=process"],
        "cache": ["/api/live/status?light=1&scope=process"],
        "telemetry": ["/api/live/status?light=1&scope=process", "/api/telemetry/report?days=30&scope=process"],
        "full": ["/api/live/status?light=1&scope=process", "/api/capabilities"],
        "agent_state": ["/api/live/status?light=1&scope=process", ("status", {"detail": "agent_state"})],
    }
    for action, expected in expected_calls.items():
        calls.clear()
        result = mcp_server.local_ai_status(action=action, detail="telemetry")
        assert result["success"] is True
        assert calls == expected


def test_pubsub_poll_http_payload_requires_bounded_sequence_cursor():
    import pytest

    from local_ai_hub.http_server import Handler, RequestBodyError

    path = "/api/coord/pubsub_poll"
    Handler._validate_payload(path, {"after_seq": 17, "limit": 50})
    Handler._validate_payload(path, {"after_seq": (1 << 63) - 1})
    Handler._validate_payload(path, {})

    for invalid in (True, -1, 1.5, "17", 1 << 63):
        with pytest.raises(RequestBodyError):
            Handler._validate_payload(path, {"after_seq": invalid})


def test_pubsub_service_uses_app_store_and_preserves_sequence_gap(monkeypatch):
    from local_ai_hub.agent_events import SwarmPubSub
    from local_ai_hub.services import LocalAIServices

    app_store = object()
    calls = []
    page = {
        "success": True,
        "topic": "build",
        "messages": [],
        "after_seq": 3,
        "next_seq": 3,
        "last_seq": 12,
        "has_more": False,
        "has_gap": True,
        "first_retained_seq": 8,
        "gap": {
            "reason": "retention",
            "requested_after_seq": 3,
            "first_retained_seq": 8,
            "last_seq": 12,
        },
    }

    class Bus:
        def publish(self, topic, message, *, sender):
            calls.append(("publish", topic, message, sender))
            return {"success": True}

        def poll(self, topic, *, after_seq, limit):
            calls.append(("poll", topic, after_seq, limit))
            return page

    bus = Bus()

    def get_default(cls, state_store=None):
        calls.append(("store", state_store))
        return bus

    monkeypatch.setattr(SwarmPubSub, "get_default", classmethod(get_default))
    services = object.__new__(LocalAIServices)
    services.agent_state = app_store

    assert services.pubsub_publish("build", {"event": "done"}, sender="worker")["success"] is True
    result = services.pubsub_poll("build", after_seq=3, limit=50)

    assert result == page
    assert calls == [
        ("store", app_store),
        ("publish", "build", {"event": "done"}, "worker"),
        ("store", app_store),
        ("poll", "build", 3, 50),
    ]


def test_pubsub_http_route_forwards_sequence_cursor_and_gap(monkeypatch):
    from local_ai_hub import http_server

    page = {
        "success": True,
        "topic": "build",
        "messages": [],
        "after_seq": 7,
        "next_seq": 7,
        "last_seq": 12,
        "has_more": False,
        "has_gap": True,
        "first_retained_seq": 8,
        "gap": {"reason": "retention", "requested_after_seq": 7, "first_retained_seq": 8, "last_seq": 12},
    }
    calls = []

    def pubsub_poll(topic, **kwargs):
        calls.append((topic, kwargs))
        return page

    monkeypatch.setattr(http_server, "APP", type("App", (), {
        "config": {"server": {}},
        "services": type("Services", (), {"pubsub_poll": staticmethod(pubsub_poll)})(),
    })())
    handler = object.__new__(http_server.Handler)
    handler.path = "/api/coord/pubsub_poll"
    handler.command = "POST"
    handler.headers = {"Content-Type": "application/json"}
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    handler._read_json = lambda: {"topic": "build", "after_seq": 7, "limit": 9}
    sent = []
    handler._send = lambda status, body, headers=None: sent.append((status, body))

    http_server.Handler.do_POST(handler)

    assert calls == [("build", {"after_seq": 7, "limit": 9})]
    assert sent == [(200, page)]
