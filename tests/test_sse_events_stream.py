from __future__ import annotations

import io
import json
import sqlite3
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


class BlockingWfile(MockWfile):
    def __init__(self):
        super().__init__()
        self.first_event_started = threading.Event()
        self.resume = threading.Event()
        self._blocked = False

    def write(self, b: bytes) -> int:
        written = super().write(b)
        if b.startswith(b"id:") and not self._blocked:
            self._blocked = True
            self.first_event_started.set()
            if not self.resume.wait(timeout=5.0):
                raise OSError("slow SSE consumer timed out")
        return written


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
        self.stream_finishes = []
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
        self.stream_finishes.append(success)

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
        with store._subscribers_lock:
            assert store._subscribers == []
    finally:
        http_server.APP = orig_app


def test_sse_disconnect_is_recorded_as_failure(tmp_path: Path, monkeypatch):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store.append(AgentEvent.create("task-1", "task.created", {"step": 1}, "k1"))

    class DummyApp:
        agent_state = store

    monkeypatch.setattr(http_server, "APP", DummyApp())
    handler = DummyHandler(DummyApp())
    handler.wfile.disconnect_after = b"event: task.created"

    handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=0.1)

    assert handler.stream_finishes == [False]
    with store._subscribers_lock:
        assert store._subscribers == []


def test_sse_stream_does_not_lose_event_between_replay_and_subscribe(tmp_path: Path, monkeypatch):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store.append(AgentEvent.create("task-1", "task.created", {"step": 1}, "k1"))
    original_page = store.event_page

    def page_then_publish(*args, **kwargs):
        replay = original_page(*args, **kwargs)
        store.append(AgentEvent.create("task-1", "task.updated", {"step": 2}, "k2"))
        return replay

    monkeypatch.setattr(store, "event_page", page_then_publish)

    class DummyApp:
        agent_state = store

    monkeypatch.setattr(http_server, "APP", DummyApp())
    handler = DummyHandler(DummyApp())
    handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=0.1)

    output = handler.wfile.getvalue().decode("utf-8")
    assert "event: task.updated" in output
    assert '"step":2' in output
    assert output.count("event: task.updated") == 1


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
    assert handler.stream_finishes == [True]
    with store._subscribers_lock:
        assert store._subscribers == []


def test_sse_stream_replays_all_pages_and_advances_cursor(tmp_path: Path, monkeypatch):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    for index in range(1001):
        store.append(
            AgentEvent.create(
                "task-1", "task.updated", {"step": index}, f"page-{index}"
            )
        )
    requested_cursors = []
    original_page = store.event_page

    def record_page_cursor(*args, **kwargs):
        requested_cursors.append(kwargs.get("after_seq", 0))
        return original_page(*args, **kwargs)

    monkeypatch.setattr(store, "event_page", record_page_cursor)

    class DummyApp:
        agent_state = store

    monkeypatch.setattr(http_server, "APP", DummyApp())
    handler = DummyHandler(DummyApp())
    handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=0.01)

    output = handler.wfile.getvalue().decode("utf-8")
    assert output.count("event: task.updated") == 1001
    assert "id: 1001\nevent: task.updated" in output
    assert requested_cursors == [0, 1000]


def test_sse_stream_surfaces_retention_gap_before_kind_filtered_replay(
    tmp_path: Path, monkeypatch
):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store.append(AgentEvent.create("task-1", "task.created", {"step": 1}, "old-1"))
    store.append(AgentEvent.create("task-1", "task.completed", {"step": 2}, "old-2"))
    store.append(AgentEvent.create("task-1", "task.updated", {"step": 3}, "new-3"))
    old_time = time.time() - 3 * 86400
    con = sqlite3.connect(store.db_path)
    try:
        con.execute(
            "UPDATE agent_events SET created_at = ? WHERE stream_id = ? AND seq < 3",
            (old_time, "task-1"),
        )
        con.commit()
    finally:
        con.close()
    store.cleanup(retention_days=1)

    class DummyApp:
        agent_state = store

    monkeypatch.setattr(http_server, "APP", DummyApp())
    handler = DummyHandler(DummyApp())
    handler._stream_agent_events(
        stream_id="task-1", kind="task.updated", after_seq=0, timeout=0.01
    )

    output = handler.wfile.getvalue().decode("utf-8")
    gap_index = output.index("event: stream.gap")
    replay_index = output.index("event: task.updated")
    assert gap_index < replay_index
    assert '"from_seq":1' in output
    assert '"to_seq":2' in output


def test_sse_stream_tracks_live_cursors_per_stream(tmp_path: Path, monkeypatch):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    subscribed = threading.Event()
    original_subscribe = store.subscribe

    def capture_subscribe(maxsize=100):
        result = original_subscribe(maxsize=maxsize)
        subscribed.set()
        return result

    monkeypatch.setattr(store, "subscribe", capture_subscribe)

    class DummyApp:
        agent_state = store

    monkeypatch.setattr(http_server, "APP", DummyApp())
    handler = DummyHandler(DummyApp())
    handler.wfile = BlockingWfile()
    worker = threading.Thread(
        target=handler._stream_agent_events, kwargs={"timeout": 1.0}
    )
    worker.start()
    assert subscribed.wait(timeout=1.0)
    store.append(AgentEvent.create("task-a", "task.created", {"n": 1}, "a-1"))
    assert handler.wfile.first_event_started.wait(timeout=1.0)
    store.append(AgentEvent.create("task-b", "task.updated", {"n": 2}, "b-1"))
    handler.wfile.resume.set()
    worker.join(timeout=2.0)

    assert not worker.is_alive()
    output = handler.wfile.getvalue().decode("utf-8")
    assert "event: task.created" in output
    assert "event: task.updated" in output
    assert '"n":2' in output


def test_sse_slow_consumer_receives_overflow_gap_even_with_kind_filter(
    tmp_path: Path, monkeypatch
):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    subscribed = threading.Event()
    original_subscribe = store.subscribe

    def capture_subscribe(maxsize=100):
        result = original_subscribe(maxsize=4)
        subscribed.set()
        return result

    monkeypatch.setattr(store, "subscribe", capture_subscribe)

    class DummyApp:
        agent_state = store

    monkeypatch.setattr(http_server, "APP", DummyApp())
    handler = DummyHandler(DummyApp())
    handler.wfile = BlockingWfile()
    worker = threading.Thread(
        target=handler._stream_agent_events,
        kwargs={"kind": "task.updated", "timeout": 5.0},
    )
    worker.start()
    assert subscribed.wait(timeout=1.0)
    try:
        store.append(AgentEvent.create("task-slow", "task.updated", {"n": 1}, "slow-1"))
        assert handler.wfile.first_event_started.wait(timeout=1.0)
        for index in range(2, 10):
            store.append(
                AgentEvent.create(
                    "task-slow", "task.updated", {"n": index}, f"slow-{index}"
                )
            )
    finally:
        handler.wfile.resume.set()
        worker.join(timeout=7.0)

    assert not worker.is_alive()
    output = handler.wfile.getvalue().decode("utf-8")
    assert "event: stream.gap" in output
    gap_line = next(
        line[len("data: "):]
        for line in output.splitlines()
        if line.startswith("data: ") and '"gap_ranges"' in line
    )
    gap = json.loads(gap_line)
    assert gap["payload"]["lost_count"] > 0
    assert gap["payload"]["replay_required"] is True


def test_client_stream_events_parsing(monkeypatch):
    from unittest.mock import MagicMock
    from local_ai_hub.client import HubClient

    client = HubClient.__new__(HubClient)
    client.base_url = "http://127.0.0.1:11435"
    client.api_token = "tok"
    client.max_request_timeout = 60.0
    client.tenant = "default"
    client.agent = "test"

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


def test_client_stream_events_closes_response_on_cancellation(monkeypatch):
    from local_ai_hub.client import HubClient

    client = HubClient.__new__(HubClient)
    client.base_url = "http://127.0.0.1:11435"
    client.api_token = ""
    client.max_request_timeout = 60.0
    client.tenant = "default"
    client.agent = "test"
    cancel_event = threading.Event()

    class BlockingResponse:
        def __init__(self):
            self.iterating = threading.Event()
            self.closed = threading.Event()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

        def __iter__(self):
            self.iterating.set()
            self.closed.wait(timeout=2.0)
            return iter(())

        def close(self):
            self.closed.set()

    response = BlockingResponse()
    monkeypatch.setattr("local_ai_hub.client.urlopen", lambda *_args, **_kwargs: response)
    worker = threading.Thread(
        target=lambda: list(
            client.stream_events(timeout=5.0, cancel_event=cancel_event)
        )
    )
    worker.start()
    assert response.iterating.wait(timeout=1.0)
    cancel_event.set()

    assert response.closed.wait(timeout=1.0)
    worker.join(timeout=1.0)
    assert not worker.is_alive()
