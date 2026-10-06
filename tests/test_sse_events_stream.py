from __future__ import annotations

import sqlite3
import io
import json
import threading
import time
from pathlib import Path

import pytest

from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub import http_server


class MockWfile(io.BytesIO):
    def __init__(self):
        super().__init__()
        self.flushed = False
        self.disconnect_after: bytes | None = None

    def flush(self):
        self.flushed = True

    def write(self, b: bytes) -> int:
        res = super().write(b)
        if self.disconnect_after and self.disconnect_after in self.getvalue():
            raise OSError("client disconnected")
        return res


class DummyHandler:
    def __init__(self, app):
        self.wfile = MockWfile()
        self.headers_sent = []
        self.response_code = None
        self._trace_id = "test-trace"
        self._request_started = time.perf_counter()
        self._trace_request_id = "req-1"
        self._journal_request_id = "j-1"
        self._telemetry_finished = False
        self._debug_trace_finished = False
        self._journal_finished = False
        self.finished_stream_request = None
        self._app = app

    def _tenant(self):
        return "test-tenant"

    def _agent(self):
        return "test-agent"

    def send_response(self, code):
        self.response_code = code

    def send_header(self, k, v):
        self.headers_sent.append((k, v))

    def _common_headers(self):
        pass

    def end_headers(self):
        pass

    def _finish_stream_request(self, success, error=""):
        self.finished_stream_request = (success, error)

    def _stream_agent_events(self, stream_id="", kind="", after_seq=0, timeout=0.0):
        http_server.Handler._stream_agent_events(
            self, stream_id=stream_id, kind=kind, after_seq=after_seq, timeout=timeout
        )


def test_sse_stream_disabled_is_terminal_403_without_stream_headers(monkeypatch):
    class DisabledState:
        enabled = False

    class DisabledApp:
        agent_state = DisabledState()

    app = DisabledApp()
    responses = []
    monkeypatch.setattr(http_server, "APP", app)
    handler = DummyHandler(app)
    handler._send = lambda status, data: responses.append((status, data))

    handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=0.05)

    assert responses == [(403, {
        "success": False,
        "error": "agent_state is disabled",
        "terminal": True,
        "retryable": False,
    })]
    assert handler.headers_sent == []
    assert handler.wfile.getvalue() == b""


def test_sse_http_route_rejects_disabled_agent_state_before_stream(monkeypatch):
    app = type("App", (), {})()
    app.agent_state = type("DisabledState", (), {"enabled": False})()
    app.config = {}
    responses = []
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server.Handler, "_begin_trace", lambda self, _path: None)
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)
    monkeypatch.setattr(
        http_server.Handler,
        "_send",
        lambda self, status, data, **_kwargs: responses.append((status, data)),
    )
    monkeypatch.setattr(
        http_server.Handler,
        "_stream_agent_events",
        lambda self, **_kwargs: pytest.fail("disabled agent_state must not start SSE streaming"),
    )
    handler = object.__new__(http_server.Handler)
    handler.path = "/api/agent-state/events/stream?stream_id=task-1"

    http_server.Handler.do_GET(handler)

    assert responses == [(403, {
        "success": False,
        "error": "agent_state is disabled",
        "terminal": True,
        "retryable": False,
    })]


def test_sse_stream_replays_and_receives_live_events(tmp_path: Path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store.append(AgentEvent.create("task-1", "task.created", {"step": 1}, "k1"))

    class DummyApp:
        agent_state = store

    orig_app = http_server.APP
    http_server.APP = DummyApp()
    try:
        handler = DummyHandler(DummyApp())
        handler.wfile.disconnect_after = b"task.updated"

        def _publish_delayed():
            for _ in range(200):
                if b"event: task.created" in handler.wfile.getvalue():
                    break
                time.sleep(0.01)
            store.append(AgentEvent.create("task-1", "task.updated", {"step": 2}, "k2"))

        t = threading.Thread(target=_publish_delayed)
        t.start()

        # Stream with sufficient timeout headroom (disconnects immediately on live event)
        handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=3.0)
        t.join()

        output = handler.wfile.getvalue().decode("utf-8")
        assert "event: task.created" in output
        assert "event: task.updated" in output
        assert '"step":1' in output
        assert '"step":2' in output
        assert handler.finished_stream_request == (False, "client disconnected")
    finally:
        http_server.APP = orig_app


def test_sse_stream_resumes_from_last_event_id_for_explicit_stream(tmp_path: Path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store.append(AgentEvent.create("task-1", "task.created", {"step": 1}, "k1"))
    store.append(AgentEvent.create("task-1", "task.updated", {"step": 2}, "k2"))

    class DummyApp:
        agent_state = store

    orig_app = http_server.APP
    http_server.APP = DummyApp()
    try:
        handler = DummyHandler(DummyApp())
        handler.headers = {"Last-Event-ID": "1"}
        handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=0.01)

        output = handler.wfile.getvalue().decode("utf-8")
        assert "event: task.created" not in output
        assert "event: task.updated" in output
    finally:
        http_server.APP = orig_app


def test_sse_stream_does_not_lose_event_between_replay_and_subscribe(tmp_path: Path, monkeypatch):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store.append(AgentEvent.create("task-1", "task.created", {"step": 1}, "k1"))
    original_event_page = store.event_page

    def event_page_after_subscribe(*args, **kwargs):
        store.append(AgentEvent.create("task-1", "task.updated", {"step": 2}, "k2"))
        return original_event_page(*args, **kwargs)

    monkeypatch.setattr(store, "event_page", event_page_after_subscribe)

    class DummyApp:
        agent_state = store

    monkeypatch.setattr(http_server, "APP", DummyApp())
    handler = DummyHandler(DummyApp())
    handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=0.1)

    output = handler.wfile.getvalue().decode("utf-8")
    assert "event: task.updated" in output
    assert '"step":2' in output


def test_sse_stream_replays_all_bounded_pages(tmp_path: Path, monkeypatch):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store._ensure_schema()
    connection = sqlite3.connect(store.db_path)
    try:
        connection.executemany(
            """INSERT INTO agent_events
               (stream_id, seq, event_id, kind, payload, idempotency_key, correlation_id, actor, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (("task-1", index, f"evt-{index}", "task.updated", "{}", f"key-{index}", "", "agent", 1.0)
             for index in range(1, 1002)),
        )
        connection.commit()
    finally:
        connection.close()

    class DummyApp:
        agent_state = store

    monkeypatch.setattr(http_server, "APP", DummyApp())
    handler = DummyHandler(DummyApp())
    handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=0.05)

    output = handler.wfile.getvalue().decode("utf-8")
    assert output.count("event: task.updated") == 1001
    assert output.count("event: replay_page") == 11
    assert "id: 1001\n" in output

def test_sse_stream_timeout_bounds_queue_wait(tmp_path: Path, monkeypatch):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")

    class DummyApp:
        agent_state = store

    monkeypatch.setattr(http_server, "APP", DummyApp())
    handler = DummyHandler(DummyApp())
    started = time.monotonic()
    handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=0.05)

    assert time.monotonic() - started < 0.5
    assert "event: stream_timeout" in handler.wfile.getvalue().decode("utf-8")


def test_client_stream_events_parsing(monkeypatch):
    from unittest.mock import MagicMock
    from local_ai_hub.client import HubClient

    client = HubClient.__new__(HubClient)
    client.base_url = "http://127.0.0.1:11435"
    client.api_token = "tok"
    client.tenant = "test-tenant"
    client.agent = "test-agent"

    sse_payload = (
        b": keep-alive\n\n"
        b"id: 1\n"
        b"event: task.created\n"
        b"data: {\"title\": \"build\", \"step\": 1}\n\n"
        b"id: 2\n"
        b"event: task.completed\n"
        b"data: {\"title\": \"build\", \"ok\": true}\n\n"
    )

    mock_resp = io.BytesIO(sse_payload)
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = lambda s, *args: None

    monkeypatch.setattr("local_ai_hub.client.urlopen", lambda req, timeout=60.0: mock_resp)

    events = list(client.stream_events(stream_id="stream-1", timeout=5.0))
    assert len(events) == 2
    assert events[0][0] == "task.created"
    assert events[0][1]["step"] == 1
    assert events[1][0] == "task.completed"
    assert events[1][1]["ok"] is True

class _T03ReplayPageState:
    def __init__(self, total: int):
        self.total = total
        self.calls = []
        self.enabled = True

    def subscribe(self, maxsize: int):
        return http_server.queue.Queue(maxsize=maxsize)

    def unsubscribe(self, subscriber) -> None:
        pass

    def event_page(self, *, stream_id, after_seq, limit, through_seq=None):
        self.calls.append((stream_id, after_seq, limit))
        high_water = self.total if through_seq is None else min(self.total, through_seq)
        last = min(after_seq + limit, high_water)
        events = [
            {"seq": seq, "kind": "task.created", "stream_id": stream_id, "payload": {}}
            for seq in range(after_seq + 1, last + 1)
        ]
        return {
            "success": True,
            "events": events,
            "first_retained_seq": 1,
            "last_seq": self.total,
            "next_seq": last,
            "has_more": last < high_water,
            "cursor_reset": False,
            "gap_ranges": [],
        }


def test_sse_future_cursor_resets_and_replays_real_agent_event_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store.append(AgentEvent.create("task-1", "task.created", {"step": 1}, "k1"))
    store.append(AgentEvent.create("task-1", "task.updated", {"step": 2}, "k2"))

    class DummyApp:
        agent_state = store
        config = {}

    monkeypatch.setattr(http_server, "APP", DummyApp())
    handler = DummyHandler(DummyApp())
    handler._stream_agent_events(stream_id="task-1", after_seq=99, timeout=0.05)

    output = handler.wfile.getvalue().decode("utf-8")
    assert "id: 0\nevent: replay_cursor_reset" in output
    assert '"requested_after_seq":99' in output
    assert '"last_seq":2' in output
    assert '"resume_after_seq":0' in output
    assert "id: 1\nevent: task.created" in output
    assert "id: 2\nevent: task.updated" in output


def test_sse_replay_has_more_caps_without_probe_and_false_stops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = _T03ReplayPageState(total=http_server.SSE_REPLAY_MAX_EVENTS + 1)

    class DummyApp:
        agent_state = state
        config = {}

    monkeypatch.setattr(http_server, "APP", DummyApp())
    handler = DummyHandler(DummyApp())
    handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=0.05)

    output = handler.wfile.getvalue().decode("utf-8")
    assert output.count("event: task.created") == http_server.SSE_REPLAY_MAX_EVENTS
    assert f"id: {http_server.SSE_REPLAY_MAX_EVENTS}\nevent: replay_limit" in output
    assert '"replay_limit":10000' in output
    assert state.calls == [
        ("task-1", after_seq, http_server.AGENT_EVENT_PAGE_MAX_LIMIT)
        for after_seq in range(0, http_server.SSE_REPLAY_MAX_EVENTS, http_server.AGENT_EVENT_PAGE_MAX_LIMIT)
    ]
    assert ("task-1", http_server.SSE_REPLAY_MAX_EVENTS, 1) not in state.calls

    short = _T03ReplayPageState(total=http_server.AGENT_EVENT_PAGE_MAX_LIMIT)

    class ShortApp:
        agent_state = short
        config = {}

    monkeypatch.setattr(http_server, "APP", ShortApp())
    short_handler = DummyHandler(ShortApp())
    short_handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=0.05)
    assert len(short.calls) == 1
    assert "event: replay_limit" not in short_handler.wfile.getvalue().decode("utf-8")
