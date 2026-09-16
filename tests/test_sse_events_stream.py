from __future__ import annotations

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
        pass

    def _stream_agent_events(self, stream_id="", kind="", after_seq=0, timeout=0.0):
        http_server.Handler._stream_agent_events(
            self, stream_id=stream_id, kind=kind, after_seq=after_seq, timeout=timeout
        )


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
    finally:
        http_server.APP = orig_app


def test_sse_stream_does_not_lose_event_between_replay_and_subscribe(tmp_path: Path, monkeypatch):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store.append(AgentEvent.create("task-1", "task.created", {"step": 1}, "k1"))
    original_events = store.events

    def events_then_publish(*args, **kwargs):
        replay = original_events(*args, **kwargs)
        store.append(AgentEvent.create("task-1", "task.updated", {"step": 2}, "k2"))
        return replay

    monkeypatch.setattr(store, "events", events_then_publish)

    class DummyApp:
        agent_state = store

    monkeypatch.setattr(http_server, "APP", DummyApp())
    handler = DummyHandler(DummyApp())
    handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=0.1)

    output = handler.wfile.getvalue().decode("utf-8")
    assert "event: task.updated" in output
    assert '"step":2' in output


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
