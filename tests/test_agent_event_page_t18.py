from __future__ import annotations

import json
import sqlite3
import threading
from types import SimpleNamespace
import urllib.request

from local_ai_hub import http_server
from local_ai_hub.agent_events import AgentEvent, AgentStateStore


EVENT_FIELDS = {
    "event_id", "stream_id", "kind", "payload", "idempotency_key",
    "correlation_id", "actor", "created_at", "seq",
}


def _append(store: AgentStateStore, count: int = 3) -> None:
    for index in range(1, count + 1):
        result = store.append(AgentEvent.create("stream-1", "task.updated", {"step": index}, f"key-{index}"))
        assert result.error is None


def test_event_page_paginates_and_keeps_canonical_event_fields(tmp_path) -> None:
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    _append(store)

    first = store.event_page("stream-1", after_seq=0, limit=2)
    second = store.event_page("stream-1", after_seq=first["next_seq"], limit=2)
    clamped = store.event_page("stream-1", after_seq=0, limit=0)

    assert first == {
        "success": True,
        "events": [event.to_dict() for event in store.events("stream-1", limit=2)],
        "next_seq": 2,
        "first_retained_seq": 1,
        "last_seq": 3,
        "has_more": True,
        "gap_ranges": [],
        "cursor_reset": False,
    }
    assert {key for key in second["events"][0]} == EVENT_FIELDS
    assert [event["seq"] for event in second["events"]] == [3]
    assert second["next_seq"] == 3
    assert second["has_more"] is False
    assert [event["seq"] for event in clamped["events"]] == [1]
    assert clamped["has_more"] is True


def test_event_page_reports_gaps_and_resets_cursor_past_last_seq(tmp_path) -> None:
    database = tmp_path / "agent_state.sqlite3"
    store = AgentStateStore(database)
    _append(store)
    connection = sqlite3.connect(database)
    try:
        connection.execute("DELETE FROM agent_events WHERE stream_id=? AND seq=2", ("stream-1",))
        connection.commit()
    finally:
        connection.close()

    page = store.event_page("stream-1", after_seq=-5, limit=10)
    reset = store.event_page("stream-1", after_seq=99, limit=10)

    assert [event["seq"] for event in page["events"]] == [1, 3]
    assert page["gap_ranges"] == [{"from_seq": 2, "to_seq": 2}]
    assert reset["cursor_reset"] is True
    assert [event["seq"] for event in reset["events"]] == [1, 3]
    assert reset["next_seq"] == 3


def test_http_events_route_returns_event_page_envelope(monkeypatch, tmp_path) -> None:
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    _append(store)
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={}, agent_state=store))
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/agent-state/events?stream_id=stream-1&after_seq=1&limit=1"
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {}
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    handler.responses = []
    handler._send = lambda status, payload: handler.responses.append((status, payload))

    handler.do_GET()

    status, payload = handler.responses[0]
    assert status == 200
    assert set(payload) == {
        "success", "events", "next_seq", "first_retained_seq", "last_seq",
        "has_more", "gap_ranges", "cursor_reset",
    }
    assert payload["events"][0]["seq"] == 2
    assert set(payload["events"][0]) == EVENT_FIELDS

    handler.path = "/api/agent-state/events?stream_id=stream-1&after_seq=invalid&limit=0"
    handler.responses.clear()
    handler.do_GET()
    status, payload = handler.responses[0]
    assert status == 200
    assert [event["seq"] for event in payload["events"]] == [1]
    assert payload["next_seq"] == 1
    assert payload["has_more"] is True

    disabled = AgentStateStore(tmp_path / "disabled.sqlite3", enabled=False)
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={}, agent_state=disabled))
    handler.path = "/api/agent-state/events?stream_id=stream-1&after_seq=8"
    handler.responses.clear()
    handler.do_GET()
    status, payload = handler.responses[0]
    assert status == 403
    assert payload["success"] is False
    assert payload["next_seq"] == 8
    assert payload["error"]["code"] == "agent_state_disabled"


def test_http_event_page_is_serialized_over_live_http(monkeypatch, tmp_path) -> None:
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    _append(store)
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={}, agent_state=store))
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)

    class TestHandler(http_server.Handler):
        def _require_authorized(self) -> bool:
            return True

    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), TestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/api/agent-state/events?stream_id=stream-1&after_seq=1&limit=1"
        with urllib.request.urlopen(url, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["success"] is True
        assert payload["next_seq"] == 2
        assert payload["events"][0]["seq"] == 2
        assert set(payload["events"][0]) == EVENT_FIELDS
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def _route_event_page(monkeypatch, store: AgentStateStore, query: str):
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={}, agent_state=store))
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/agent-state/events?" + query
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {}
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    handler.responses = []
    handler._send = lambda status, payload: handler.responses.append((status, payload))
    handler.do_GET()
    return handler.responses[0]


def test_http_event_page_holds_initial_snapshot_when_events_append_between_pages(monkeypatch, tmp_path) -> None:
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    for index in range(2):
        result = store.append(AgentEvent.create("stream-1", "task.updated", {"index": index}, f"key-{index}"))
        assert result.error is None

    status, first = _route_event_page(monkeypatch, store, "stream_id=stream-1&after_seq=0&limit=1")
    assert status == 200
    snapshot_seq = first["last_seq"]
    assert first["has_more"] is True

    appended = store.append(AgentEvent.create("stream-1", "task.updated", {"index": 2}, "key-2"))
    assert appended.error is None
    status, second = _route_event_page(
        monkeypatch,
        store,
        f"stream_id=stream-1&after_seq={first['next_seq']}&through_seq={snapshot_seq}&limit=10",
    )

    assert status == 200
    assert [event["seq"] for event in second["events"]] == [snapshot_seq]
    assert second["next_seq"] == snapshot_seq
    assert second["has_more"] is False


def test_http_event_page_caps_exact_serialized_bytes_without_skipping_rows(monkeypatch, tmp_path) -> None:
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    payload = {"blob": "x" * 60_000}
    for index in range(1, 31):
        result = store.append(AgentEvent.create("stream-1", "task.updated", payload, f"key-{index}"))
        assert result.error is None

    status, first = _route_event_page(monkeypatch, store, "stream_id=stream-1&after_seq=0&limit=10000")
    first_size = len(http_server._json_bytes(first))
    status2, second = _route_event_page(
        monkeypatch, store, f"stream_id=stream-1&after_seq={first['next_seq']}&limit=10000"
    )

    assert status == status2 == 200
    assert first_size <= http_server.AGENT_EVENT_PAGE_MAX_BYTES
    assert len(http_server._json_bytes(second)) <= http_server.AGENT_EVENT_PAGE_MAX_BYTES
    assert first["has_more"] is True
    assert [event["seq"] for event in first["events"]] == list(range(1, first["next_seq"] + 1))
    assert second["events"][0]["seq"] == first["next_seq"] + 1


def test_http_event_page_clamps_external_limit_before_store(monkeypatch) -> None:
    class RecordingStore:
        received_limit = None

        def event_page(self, **kwargs):
            self.received_limit = kwargs["limit"]
            self.received_through_seq = kwargs.get("through_seq")
            return {
                "success": True, "events": [], "next_seq": 0,
                "first_retained_seq": 0, "last_seq": 0, "has_more": False,
                "gap_ranges": [], "cursor_reset": False,
            }

    store = RecordingStore()
    status, _page = _route_event_page(monkeypatch, store, "stream_id=stream-1&limit=10000")

    assert status == 200
    assert store.received_limit == http_server.AGENT_EVENT_PAGE_MAX_LIMIT


def test_http_event_page_forwards_snapshot_upper_bound(monkeypatch) -> None:
    class RecordingStore:
        received_kwargs = None

        def event_page(self, **kwargs):
            self.received_kwargs = kwargs
            return {
                "success": True, "events": [], "next_seq": 0,
                "first_retained_seq": 0, "last_seq": 3, "has_more": False,
                "gap_ranges": [], "cursor_reset": False,
            }

    store = RecordingStore()
    status, _page = _route_event_page(
        monkeypatch, store, "stream_id=stream-1&after_seq=1&through_seq=3&limit=10"
    )

    assert status == 200
    assert store.received_kwargs == {"stream_id": "stream-1", "after_seq": "1", "limit": 10, "through_seq": "3"}


def test_http_event_page_metadata_oversize_returns_413_without_advancing_cursor(monkeypatch, tmp_path) -> None:
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    event = AgentEvent.create("stream-1", "task.updated", {"ok": True}, "key-1", actor="m" * (2 * 1024 * 1024))
    assert store.append(event).error is None

    status, page = _route_event_page(monkeypatch, store, "stream_id=stream-1&after_seq=0&limit=10000")

    assert status == 413
    assert len(http_server._json_bytes(page)) <= http_server.AGENT_EVENT_PAGE_MAX_BYTES
    assert page["events"] == []
    assert page["next_seq"] == 0
    assert page["has_more"] is True
    assert page["error"]["code"] == "agent_event_page_too_large"


def test_disabled_event_page_returns_stable_error_envelope(tmp_path) -> None:
    store = AgentStateStore(tmp_path / "agent_state.sqlite3", enabled=False)

    result = store.event_page("stream-1", after_seq=8, limit=4)

    assert result == {
        "success": False,
        "events": [],
        "next_seq": 8,
        "first_retained_seq": 0,
        "last_seq": 0,
        "has_more": False,
        "gap_ranges": [],
        "cursor_reset": False,
        "error": {"code": "agent_state_disabled", "message": "agent state is disabled"},
    }


def test_event_page_resets_cursor_when_stream_has_no_retained_events(tmp_path) -> None:
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store._ensure_schema()

    result = store.event_page("stream-1", after_seq=8)

    assert result["success"] is True
    assert result["events"] == []
    assert result["cursor_reset"] is True
    assert result["next_seq"] == 0


def test_event_page_caps_limit_at_ten_thousand(tmp_path) -> None:
    database = tmp_path / "agent_state.sqlite3"
    store = AgentStateStore(database)
    store._ensure_schema()
    connection = sqlite3.connect(database)
    try:
        connection.executemany(
            """INSERT INTO agent_events
               (stream_id, seq, event_id, kind, payload, idempotency_key, correlation_id, actor, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (("stream-1", index, f"evt-{index}", "task.updated", "{}", f"key-{index}", "", "agent", 1.0)
             for index in range(1, 10_002)),
        )
        connection.commit()
    finally:
        connection.close()

    page = store.event_page("stream-1", after_seq=0, limit=1_000_000)

    assert len(page["events"]) == 10_000
    assert page["next_seq"] == 10_000
    assert page["has_more"] is True
