from __future__ import annotations

import io
import json
import queue
import threading
import time
from pathlib import Path
from types import SimpleNamespace

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


class MockConnection:
    def __init__(self):
        self.timeout = None
        self.timeout_history = []

    def gettimeout(self):
        return self.timeout

    def settimeout(self, timeout):
        self.timeout = timeout
        self.timeout_history.append(timeout)


class DummyHandler:
    def __init__(self, app):
        self.wfile = MockWfile()
        self.connection = MockConnection()
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

    def _run_with_stream_write_deadline(self, deadline, write):
        http_server.Handler._run_with_stream_write_deadline(self, deadline, write)

    def _write_stream_bytes(self, data, deadline):
        http_server.Handler._write_stream_bytes(self, data, deadline)

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
        assert not store._subscribers
    finally:
        http_server.APP = orig_app


def test_sse_future_cursor_resets_and_replays_real_agent_event_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store.append(AgentEvent.create("task-1", "task.created", {"step": 1}, "k1"))
    store.append(AgentEvent.create("task-1", "task.updated", {"step": 2}, "k2"))
    app = SimpleNamespace(agent_state=store, config={})
    monkeypatch.setattr(http_server, "APP", app)
    handler = DummyHandler(app)

    handler._stream_agent_events(stream_id="task-1", after_seq=99, timeout=0.05)

    output = handler.wfile.getvalue().decode("utf-8")
    assert "id: 0\nevent: replay_cursor_reset" in output
    assert '"requested_after_seq":99' in output
    assert '"last_seq":2' in output
    assert '"resume_after_seq":0' in output
    assert "id: 1\nevent: task.created" in output
    assert "id: 2\nevent: task.updated" in output


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
    events = store.events

    def delayed_events(*args, **kwargs):
        time.sleep(0.06)
        return events(*args, **kwargs)

    monkeypatch.setattr(store, "events", delayed_events)

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
    client.max_request_timeout = 60.0

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


def _http_stream_handler(monkeypatch, path: str, headers: dict[str, str]):
    app = SimpleNamespace(agent_state=SimpleNamespace(enabled=True), config={})
    monkeypatch.setattr(http_server, "APP", app)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = path
    handler.headers = headers
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    stream_calls = []
    response_calls = []
    handler._stream_agent_events = lambda **kwargs: stream_calls.append(kwargs)
    handler._send = lambda status, body: response_calls.append((status, body))
    return handler, stream_calls, response_calls


def test_http_sse_uses_last_event_id_over_query_cursor(monkeypatch):
    handler, stream_calls, response_calls = _http_stream_handler(
        monkeypatch,
        "/api/agent-state/events/stream?stream_id=task-1&after_seq=3&timeout=0.1",
        {"Last-Event-ID": "7"},
    )

    handler.do_GET()

    assert response_calls == []
    assert len(stream_calls) == 1
    assert stream_calls[0]["after_seq"] == 7
    assert stream_calls[0]["stream_id"] == "task-1"


def test_http_sse_rejects_invalid_last_event_id(monkeypatch):
    handler, stream_calls, response_calls = _http_stream_handler(
        monkeypatch,
        "/api/agent-state/events/stream?stream_id=task-1&after_seq=3",
        {"Last-Event-ID": "-1"},
    )

    handler.do_GET()

    assert stream_calls == []
    assert response_calls[0][0] == 400
    assert "Last-Event-ID" in response_calls[0][1]["error"]


@pytest.mark.parametrize(
    ("path", "headers"),
    [
        ("/api/agent-state/events/stream?after_seq=3", {}),
        ("/api/agent-state/events/stream", {"Last-Event-ID": "3"}),
    ],
)
def test_http_sse_rejects_resume_cursor_without_stream_id(monkeypatch, path, headers):
    handler, stream_calls, response_calls = _http_stream_handler(monkeypatch, path, headers)

    handler.do_GET()

    assert stream_calls == []
    assert response_calls[0][0] == 400
    assert "stream_id is required" in response_calls[0][1]["error"]


def test_http_sse_accepts_maximum_last_event_id(monkeypatch):
    handler, stream_calls, response_calls = _http_stream_handler(
        monkeypatch,
        "/api/agent-state/events/stream?stream_id=task-1",
        {"Last-Event-ID": str(http_server.MAX_EVENT_SEQUENCE)},
    )

    handler.do_GET()

    assert response_calls == []
    assert stream_calls[0]["after_seq"] == http_server.MAX_EVENT_SEQUENCE


def test_http_sse_rejects_last_event_id_above_maximum(monkeypatch):
    handler, stream_calls, response_calls = _http_stream_handler(
        monkeypatch,
        "/api/agent-state/events/stream?stream_id=task-1",
        {"Last-Event-ID": str(http_server.MAX_EVENT_SEQUENCE + 1)},
    )

    handler.do_GET()

    assert stream_calls == []
    assert response_calls[0][0] == 400


class ReplayEvent:
    def __init__(self, seq: int, kind: str = "task.created"):
        self.seq = seq
        self.stream_id = "task-1"
        self.kind = kind

    def to_dict(self):
        return {"seq": self.seq, "stream_id": self.stream_id, "kind": self.kind}


class PagedReplayState:
    enabled = True

    def __init__(self, *, total: int, gap_after: int | None = None, gap_size: int = 0):
        self.total = total
        self.gap_after = gap_after
        self.gap_size = gap_size
        self.calls: list[tuple[int, int]] = []

    def subscribe(self, maxsize: int):
        return queue.Queue(maxsize=maxsize)

    def unsubscribe(self, subscriber) -> None:
        return None

    def events(self, stream_id: str, after_seq: int = 0, limit: int = 1000):
        self.calls.append((after_seq, limit))
        first = after_seq + 1
        if self.gap_after is not None and after_seq == self.gap_after:
            first += self.gap_size
        last = min(self.total, after_seq + limit + (first - after_seq - 1))
        return [ReplayEvent(seq) for seq in range(first, last + 1)]


class QueuedReplayState(PagedReplayState):
    def __init__(self, *, total: int, queued_events=()):
        super().__init__(total=total)
        self.queued_events = list(queued_events)
        self.unsubscribe_calls = 0

    def subscribe(self, maxsize: int):
        subscriber = queue.Queue(maxsize=maxsize)
        for event in self.queued_events:
            subscriber.put_nowait(event)
        return subscriber

    def unsubscribe(self, subscriber) -> None:
        self.unsubscribe_calls += 1


class EmptyPrunedReplayState(QueuedReplayState):
    def __init__(self):
        super().__init__(total=0)
        self.event_page_calls = []

    def event_page(self, stream_id: str, after_seq: int = 0, limit: int = 1000):
        self.event_page_calls.append((stream_id, after_seq, limit))
        return {
            "success": True,
            "events": [],
            "gap_ranges": [],
            "gap": True,
            "has_gap": True,
            "first_retained_seq": 101,
            "last_seq": 100,
            "has_more": False,
        }

    def events(self, stream_id: str, after_seq: int = 0, limit: int = 1000):
        raise AssertionError("event_page metadata must serve empty retained history")


class MetadataReplayState(PagedReplayState):
    def __init__(self, *, total: int):
        super().__init__(total=total)
        self.event_page_calls = []

    def event_page(self, stream_id: str, after_seq: int = 0, limit: int = 1000):
        self.event_page_calls.append((stream_id, after_seq, limit))
        events = super().events(stream_id, after_seq, limit)
        first_retained_seq = 1 if self.total else 0
        has_gap = bool(first_retained_seq and after_seq < first_retained_seq - 1)
        return {
            "success": True,
            "events": events,
            "gap_ranges": [],
            "gap": has_gap,
            "has_gap": has_gap,
            "first_retained_seq": first_retained_seq,
            "last_seq": self.total,
            "has_more": after_seq + len(events) < self.total,
        }


def test_sse_http_event_page_failure_reports_unknown_gap_without_legacy_replay(monkeypatch):
    class UnavailableReplayState(QueuedReplayState):
        def __init__(self):
            super().__init__(total=0)
            self.legacy_calls = 0

        def event_page(self, stream_id: str, after_seq: int = 0, limit: int = 1000):
            return {
                "success": False,
                "events": [],
                "gap_ranges": [],
                "error": "agent_state schema is unavailable",
            }

        def events(self, stream_id: str, after_seq: int = 0, limit: int = 1000):
            self.legacy_calls += 1
            raise AssertionError("legacy events may initialize an unavailable schema")

    state = UnavailableReplayState()
    app = SimpleNamespace(agent_state=state, config={})
    monkeypatch.setattr(http_server, "APP", app)
    handler = DummyHandler(app)

    handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=0.01)

    output = handler.wfile.getvalue().decode("utf-8")
    assert state.legacy_calls == 0
    assert "event: replay_gap" in output
    assert '"stream_id":"task-1"' in output
    assert '"unknown_range":true' in output
    assert '"replay_unavailable":true' in output
    assert handler.close_connection is True


def test_sse_http_emits_interior_retention_gap_from_event_page(monkeypatch):
    class InteriorGapReplayState(PagedReplayState):
        def __init__(self):
            super().__init__(total=3)
            self.event_page_calls = []

        def event_page(self, stream_id: str, after_seq: int = 0, limit: int = 1000):
            self.event_page_calls.append((stream_id, after_seq, limit))
            return {
                "success": True,
                "events": [ReplayEvent(1), ReplayEvent(3)],
                "gap": True,
                "has_gap": True,
                "first_retained_seq": 1,
                "last_seq": 3,
                "has_more": False,
                "gap_ranges": [
                    {"missing_from_seq": 2, "missing_through_seq": 2},
                ],
            }

    state = InteriorGapReplayState()
    app = SimpleNamespace(agent_state=state, config={})
    monkeypatch.setattr(http_server, "APP", app)
    handler = DummyHandler(app)

    handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=0.05)

    output = handler.wfile.getvalue().decode("utf-8")
    event_one = output.index("id: 1\nevent: task.created")
    gap = output.index("id: 2\nevent: replay_gap")
    event_three = output.index("id: 3\nevent: task.created")
    assert event_one < gap < event_three
    assert '"missing_from_seq":2' in output
    assert '"missing_through_seq":2' in output
    assert state.event_page_calls == [("task-1", 0, http_server.SSE_REPLAY_PAGE_SIZE)]


def test_sse_http_emits_gap_for_fully_pruned_tail(monkeypatch):
    class FullyPrunedReplayState(PagedReplayState):
        def __init__(self):
            super().__init__(total=3)
            self.event_page_calls = []

        def event_page(self, stream_id: str, after_seq: int = 0, limit: int = 1000):
            self.event_page_calls.append((stream_id, after_seq, limit))
            return {
                "success": True,
                "events": [],
                "gap": True,
                "has_gap": True,
                "first_retained_seq": 0,
                "last_seq": 3,
                "has_more": False,
                "gap_ranges": [
                    {"missing_from_seq": 1, "missing_through_seq": 3},
                ],
            }

    state = FullyPrunedReplayState()
    app = SimpleNamespace(agent_state=state, config={})
    monkeypatch.setattr(http_server, "APP", app)
    handler = DummyHandler(app)

    handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=0.05)

    output = handler.wfile.getvalue().decode("utf-8")
    assert "id: 3\nevent: replay_gap" in output
    assert '"missing_from_seq":1' in output
    assert '"missing_through_seq":3' in output
    assert '"first_available_seq":4' in output
    assert state.event_page_calls == [("task-1", 0, http_server.SSE_REPLAY_PAGE_SIZE)]


def test_sse_http_future_cursor_resets_and_replays_unpaged_retained_history(monkeypatch):
    class RetainedReplayState(PagedReplayState):
        def events(self, stream_id: str, after_seq: int = 0, limit: int = 1000):
            self.calls.append((after_seq, limit))
            first = max(after_seq + 1, 101)
            last = min(self.total, first + limit - 1)
            return [ReplayEvent(seq) for seq in range(first, last + 1)]

    state = RetainedReplayState(total=105)
    app = SimpleNamespace(agent_state=state, config={})
    monkeypatch.setattr(http_server, "APP", app)
    handler = DummyHandler(app)

    handler._stream_agent_events(stream_id="task-1", after_seq=999, timeout=0.05)

    output = handler.wfile.getvalue().decode("utf-8")
    assert "id: 100\nevent: replay_cursor_reset" in output
    assert '"requested_after_seq":999' in output
    assert '"last_seq":105' in output
    assert '"resume_after_seq":100' in output
    assert '"missing_through_seq":100' in output
    assert output.count("event: task.created") == 5
    assert all(f"id: {seq}\nevent: task.created" in output for seq in range(101, 106))


def test_sse_http_maximum_cursor_bounds_fallback_queries(monkeypatch):
    state = PagedReplayState(total=105)
    app = SimpleNamespace(agent_state=state, config={})
    monkeypatch.setattr(http_server, "APP", app)
    handler = DummyHandler(app)

    handler._stream_agent_events(
        stream_id="task-1",
        after_seq=http_server.MAX_EVENT_SEQUENCE,
        timeout=0.05,
    )

    output = handler.wfile.getvalue().decode("utf-8")
    assert f'"requested_after_seq":{http_server.MAX_EVENT_SEQUENCE}' in output
    assert '"last_seq":105' in output
    assert '"resume_after_seq":0' in output
    assert all(f"id: {seq}\nevent: task.created" in output for seq in range(1, 106))
    # Initial page + first-row probe + at most 63 binary probes + replay page.
    assert len(state.calls) <= 66
    assert all(0 < limit <= 1000 for _, limit in state.calls)


def test_sse_http_replay_is_capped_at_10000_events(monkeypatch):
    state = PagedReplayState(total=12_000)
    app = SimpleNamespace(agent_state=state, config={})
    monkeypatch.setattr(http_server, "APP", app)
    handler = DummyHandler(app)

    handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=5.0)

    output = handler.wfile.getvalue().decode("utf-8")
    assert output.count("event: task.created") == 10_000
    assert f"id: 10000\nevent: replay_limit" in output
    assert '"replay_limit":10000' in output


def test_sse_http_event_page_has_more_controls_replay_continuation(monkeypatch):
    state = MetadataReplayState(total=12_000)
    app = SimpleNamespace(agent_state=state, config={})
    monkeypatch.setattr(http_server, "APP", app)
    handler = DummyHandler(app)

    handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=5.0)

    output = handler.wfile.getvalue().decode("utf-8")
    assert output.count("event: task.created") == 10_000
    assert "id: 10000\nevent: replay_limit" in output
    assert state.event_page_calls == [
        ("task-1", after_seq, http_server.SSE_REPLAY_PAGE_SIZE)
        for after_seq in range(0, 10_000, http_server.SSE_REPLAY_PAGE_SIZE)
    ]
    assert ("task-1", 10_000, 1) not in state.event_page_calls


def test_sse_http_page_without_has_more_does_not_refetch_full_page(monkeypatch):
    state = MetadataReplayState(total=http_server.SSE_REPLAY_PAGE_SIZE)

    def subscribe_with_next_event(maxsize: int):
        subscriber = queue.Queue(maxsize=maxsize)
        subscriber.put_nowait(ReplayEvent(http_server.SSE_REPLAY_PAGE_SIZE + 1, "task.updated"))
        return subscriber

    state.subscribe = subscribe_with_next_event
    app = SimpleNamespace(agent_state=state, config={})
    monkeypatch.setattr(http_server, "APP", app)
    handler = DummyHandler(app)
    handler.wfile.disconnect_after = b"id: 1001\nevent: task.updated"

    handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=5.0)

    output = handler.wfile.getvalue().decode("utf-8")
    assert "id: 1001\nevent: task.updated" in output
    assert state.event_page_calls == [("task-1", 0, http_server.SSE_REPLAY_PAGE_SIZE)]


def test_sse_http_future_cursor_resets_to_retained_window(monkeypatch):
    state = MetadataReplayState(total=3)
    app = SimpleNamespace(agent_state=state, config={})
    monkeypatch.setattr(http_server, "APP", app)
    handler = DummyHandler(app)
    handler.wfile.disconnect_after = b"id: 3\nevent: task.created"

    handler._stream_agent_events(stream_id="task-1", after_seq=99, timeout=5.0)

    output = handler.wfile.getvalue().decode("utf-8")
    assert "id: 0\nevent: replay_cursor_reset" in output
    reset_frame = next(
        frame for frame in output.split("\n\n")
        if frame.startswith("id: 0\nevent: replay_cursor_reset")
    )
    reset = json.loads(reset_frame.split("data: ", 1)[1])
    assert reset == {
        "requested_after_seq": 99,
        "last_seq": 3,
        "resume_after_seq": 0,
        "cursor_ahead": True,
    }
    event_positions = [output.index(f"id: {seq}\nevent: task.created") for seq in (1, 2, 3)]
    assert event_positions == sorted(event_positions)
    assert state.event_page_calls == [
        ("task-1", 99, http_server.SSE_REPLAY_PAGE_SIZE),
        ("task-1", 0, http_server.SSE_REPLAY_PAGE_SIZE),
    ]


def test_sse_http_sparse_kind_replay_limit_checkpoint_allows_resume(monkeypatch):
    class SparseKindReplayState(PagedReplayState):
        def events(self, stream_id: str, after_seq: int = 0, limit: int = 1000):
            events = super().events(stream_id, after_seq, limit)
            for event in events:
                if event.seq == 10_001:
                    event.kind = "task.completed"
            return events

    state = SparseKindReplayState(total=10_001)
    app = SimpleNamespace(agent_state=state, config={})
    monkeypatch.setattr(http_server, "APP", app)
    first_handler = DummyHandler(app)

    first_handler._stream_agent_events(stream_id="task-1", kind="task.completed", after_seq=0, timeout=5.0)

    first_output = first_handler.wfile.getvalue().decode("utf-8")
    assert "event: task.completed" not in first_output
    assert "id: 10000\nevent: replay_limit" in first_output

    second_handler = DummyHandler(app)
    second_handler.wfile.disconnect_after = b"id: 10001\nevent: task.completed"
    second_handler._stream_agent_events(stream_id="task-1", kind="task.completed", after_seq=10_000, timeout=5.0)

    second_output = second_handler.wfile.getvalue().decode("utf-8")
    assert "id: 10001\nevent: task.completed" in second_output


def test_sse_http_rechecks_retention_gap_after_each_replay_page(monkeypatch):
    state = PagedReplayState(total=2_000, gap_after=1_000, gap_size=10)
    app = SimpleNamespace(agent_state=state, config={})
    monkeypatch.setattr(http_server, "APP", app)
    handler = DummyHandler(app)
    handler.wfile.disconnect_after = b"event: replay_gap"

    handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=5.0)

    output = handler.wfile.getvalue().decode("utf-8")
    assert len(state.calls) >= 2
    assert state.calls[1][0] == 1_000
    assert "event: replay_gap" in output
    assert '"first_available_seq":1011' in output


def test_sse_http_reports_retention_gap_when_all_rows_pruned(monkeypatch):
    state = EmptyPrunedReplayState()
    event_page = state.event_page

    def delayed_event_page(*args, **kwargs):
        time.sleep(0.06)
        return event_page(*args, **kwargs)

    monkeypatch.setattr(state, "event_page", delayed_event_page)
    app = SimpleNamespace(agent_state=state, config={})
    monkeypatch.setattr(http_server, "APP", app)
    handler = DummyHandler(app)

    handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=0.05)

    output = handler.wfile.getvalue().decode("utf-8")
    assert state.event_page_calls == [("task-1", 0, http_server.SSE_REPLAY_PAGE_SIZE)]
    assert "id: 100\nevent: replay_gap" in output
    assert '"first_available_seq":101' in output
    assert '"retention_gap":true' in output


def test_sse_http_replays_retained_gap_after_real_store_pruning(tmp_path: Path, monkeypatch):
    from contextlib import closing
    import sqlite3

    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    for step in (1, 2, 3):
        store.append(AgentEvent.create("task-1", "task.updated", {"step": step}, f"k{step}"))

    with closing(sqlite3.connect(store.db_path)) as connection:
        connection.execute(
            "UPDATE agent_events SET created_at=? WHERE stream_id=? AND seq <= 2",
            (time.time() - (2 * 86400), "task-1"),
        )
        connection.commit()
    cleanup = store.cleanup(retention_days=1)

    assert cleanup["deleted_events"] == 2
    retained = store.events(stream_id="task-1", after_seq=0, limit=10)
    assert [event.seq for event in retained] == [3]

    app = SimpleNamespace(agent_state=store, config={})
    monkeypatch.setattr(http_server, "APP", app)
    handler = DummyHandler(app)
    handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=1.0)

    output = handler.wfile.getvalue().decode("utf-8")
    assert "id: 2\nevent: replay_gap" in output
    assert '"first_available_seq":3' in output
    assert "id: 3\nevent: task.updated" in output


@pytest.mark.parametrize("marker_seq", [None, 900])
def test_sse_http_live_queue_gap_targets_stream_and_keeps_synthetic_seq_out_of_cursor(monkeypatch, marker_seq):
    marker = AgentEvent.create(
        "agent_state",
        "agent_state.gap",
        {
            "streams": [
                {"stream_id": "task-1", "from_seq": 3, "to_seq": 5},
                {"stream_id": "task-2", "from_seq": 8, "to_seq": 9},
            ],
            "streams_truncated": True,
        },
    )
    if marker_seq is not None:
        marker = marker.with_seq(marker_seq)
    state = QueuedReplayState(total=0, queued_events=[marker])
    app = SimpleNamespace(agent_state=state, config={})
    monkeypatch.setattr(http_server, "APP", app)
    handler = DummyHandler(app)

    handler._stream_agent_events(stream_id="task-1", after_seq=2, timeout=1.0)

    output = handler.wfile.getvalue().decode("utf-8")
    frames = [frame for frame in output.split("\n\n") if frame.startswith("event: replay_gap")]
    assert len(frames) == 2
    gaps = [json.loads(frame.split("data: ", 1)[1]) for frame in frames]
    assert gaps == [
        {"stream_id": "task-1", "from_seq": 3, "to_seq": 5, "reconnect": True},
        {"stream_id": "task-1", "reconnect": True, "unknown_range": True},
    ]
    if marker_seq is not None:
        assert f"id: {marker_seq}" not in output
    assert output.count("event: replay_gap") == len(frames)
    assert handler.close_connection is True
    assert state.unsubscribe_calls == 1


def test_sse_http_malformed_success_page_reports_unknown_gap(monkeypatch):
    class MalformedReplayState(QueuedReplayState):
        def __init__(self):
            super().__init__(total=0)
            self.legacy_calls = 0

        def event_page(self, stream_id: str, after_seq: int = 0, limit: int = 1000):
            return {"success": True, "events": []}

        def events(self, stream_id: str, after_seq: int = 0, limit: int = 1000):
            self.legacy_calls += 1
            raise AssertionError("malformed page metadata must not trigger legacy replay")

    state = MalformedReplayState()
    app = SimpleNamespace(agent_state=state, config={})
    monkeypatch.setattr(http_server, "APP", app)
    handler = DummyHandler(app)

    handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=0.01)

    output = handler.wfile.getvalue().decode("utf-8")
    assert state.legacy_calls == 0
    assert "event: replay_gap" in output
    assert '"unknown_range":true' in output
    assert handler.close_connection is True


def test_sse_http_truncated_live_gap_targets_requested_stream_as_unknown(monkeypatch):
    marker = AgentEvent.create(
        "agent_state",
        "agent_state.gap",
        {
            "streams": [{"stream_id": "task-2", "from_seq": 8, "to_seq": 9}],
            "streams_truncated": True,
        },
    )
    state = QueuedReplayState(total=0, queued_events=[marker])
    app = SimpleNamespace(agent_state=state, config={})
    monkeypatch.setattr(http_server, "APP", app)
    handler = DummyHandler(app)

    handler._stream_agent_events(stream_id="task-1", after_seq=2, timeout=1.0)

    output = handler.wfile.getvalue().decode("utf-8")
    frames = [frame for frame in output.split("\n\n") if frame.startswith("event: replay_gap")]
    assert len(frames) == 1
    gap = json.loads(frames[0].split("data: ", 1)[1])
    assert gap == {"stream_id": "task-1", "reconnect": True, "unknown_range": True}
    assert output.count("event: replay_gap") == len(frames)
    assert state.unsubscribe_calls == 1


def test_sse_http_reports_live_loss_without_sequence_ranges_as_unknown(monkeypatch):
    marker = AgentEvent.create(
        "agent_state",
        "agent_state.gap",
        {
            "reason": "subscriber_queue_overflow",
            "dropped_count": 1,
            "streams": [],
        },
    )
    state = QueuedReplayState(total=0, queued_events=[marker])
    app = SimpleNamespace(agent_state=state, config={})
    monkeypatch.setattr(http_server, "APP", app)
    handler = DummyHandler(app)

    handler._stream_agent_events(stream_id="task-1", after_seq=2, timeout=1.0)

    output = handler.wfile.getvalue().decode("utf-8")
    frames = [frame for frame in output.split("\n\n") if frame.startswith("event: replay_gap")]
    assert len(frames) == 1
    gap = json.loads(frames[0].split("data: ", 1)[1])
    assert gap == {"stream_id": "task-1", "reconnect": True, "unknown_range": True}
    assert output.count("event: replay_gap") == len(frames)
    assert handler.close_connection is True
    assert state.unsubscribe_calls == 1


def test_sse_http_replay_and_live_queue_preserve_order_without_duplicates(monkeypatch):
    state = QueuedReplayState(
        total=2,
        queued_events=[ReplayEvent(2), ReplayEvent(3, "task.updated")],
    )
    app = SimpleNamespace(agent_state=state, config={})
    monkeypatch.setattr(http_server, "APP", app)
    handler = DummyHandler(app)
    handler.wfile.disconnect_after = b"id: 3\nevent: task.updated"

    handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=5.0)

    output = handler.wfile.getvalue().decode("utf-8")
    event_positions = [
        output.index("id: 1\nevent: task.created"),
        output.index("id: 2\nevent: task.created"),
        output.index("id: 3\nevent: task.updated"),
    ]
    assert event_positions == sorted(event_positions)
    assert output.count("id: 1\nevent: task.created") == 1
    assert output.count("id: 2\nevent: task.created") == 1
    assert output.count("id: 3\nevent: task.updated") == 1
    assert state.unsubscribe_calls == 1


def test_sse_http_slow_socket_write_uses_deadline_and_unsubscribes(monkeypatch):
    class SlowWfile(MockWfile):
        def __init__(self, connection):
            super().__init__()
            self.connection = connection
            self.write_timeouts = []

        def write(self, b: bytes) -> int:
            timeout = self.connection.gettimeout()
            self.write_timeouts.append(timeout)
            assert timeout is not None and timeout > 0
            time.sleep(timeout)
            raise TimeoutError("simulated slow socket")

    event = AgentEvent.create("task-1", "task.created", {"step": 1}).with_seq(1)
    state = QueuedReplayState(total=0, queued_events=[event])
    app = SimpleNamespace(agent_state=state, config={})
    monkeypatch.setattr(http_server, "APP", app)
    handler = DummyHandler(app)
    handler.wfile = SlowWfile(handler.connection)
    started = time.monotonic()

    handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=0.05)

    assert time.monotonic() - started < 0.5
    assert handler.wfile.write_timeouts
    assert all(0 < value <= 0.05 for value in handler.wfile.write_timeouts)
    assert state.unsubscribe_calls == 1
