from __future__ import annotations

from io import BytesIO
import json
import queue
from types import SimpleNamespace

from local_ai_hub import http_server
from local_ai_hub.agent_events import AgentEvent


def _route_handler(path: str, *, headers: dict[str, str] | None = None):
    handler = object.__new__(http_server.Handler)
    handler.path = path
    handler.command = "GET"
    handler.headers = headers or {}
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    handler._authorization_succeeded = True
    responses = []
    handler._send = lambda status, data: responses.append((status, data))
    return handler, responses


def test_event_list_returns_canonical_page_and_does_not_use_legacy_events(monkeypatch) -> None:
    event_data = {"event_id": "event-6", "stream_id": "task-1", "kind": "task.progress", "seq": 6}
    page = {
        "success": True,
        "events": [SimpleNamespace(to_dict=lambda: event_data)],
        "next_seq": 6,
        "first_retained_seq": 4,
        "last_seq": 10,
        "has_more": True,
        "gap_ranges": [{"from_seq": 3, "to_seq": 3}],
        "cursor_reset": False,
    }
    calls = []

    def event_page(stream_id, *, after_seq, limit):
        calls.append((stream_id, after_seq, limit))
        return page

    state = SimpleNamespace(
        enabled=True,
        event_page=event_page,
        events=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("legacy page reader used")),
    )
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(agent_state=state))
    handler, responses = _route_handler(
        "/api/agent-state/events?stream_id=task-1&after_seq=2&limit=37"
    )

    handler.do_GET()

    assert calls == [("task-1", 2, 37)]
    assert responses == [(200, {**page, "events": [event_data]})]


def test_event_list_fails_closed_and_preserves_provider_error(monkeypatch) -> None:
    error_page = {
        "success": False,
        "error": {"code": "page_read_failed", "message": "event page unavailable"},
        "terminal": False,
        "retryable": True,
    }
    legacy_calls = []
    state = SimpleNamespace(
        enabled=True,
        events=lambda **kwargs: legacy_calls.append(kwargs) or [],
        event_page=lambda *_args, **_kwargs: error_page,
    )
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(agent_state=state))
    handler, responses = _route_handler("/api/agent-state/events?stream_id=task-1&after_seq=2")

    handler.do_GET()

    assert responses == [(503, error_page)]
    assert legacy_calls == []


def test_event_stream_uses_scoped_cursor_pages_gaps_and_preserves_order(monkeypatch) -> None:
    event = AgentEvent.create("task:one", "task.progress", {"step": 7}).with_seq(7)
    calls = []

    class State:
        enabled = True

        def subscribe(self, maxsize=200):
            return queue.Queue(maxsize=maxsize)

        def event_page(self, stream_id, *, after_seq, limit):
            calls.append((stream_id, after_seq, limit))
            return {
                "success": True,
                "events": [event],
                "next_seq": 7,
                "first_retained_seq": 7,
                "last_seq": 7,
                "has_more": False,
                "gap_ranges": [{"from_seq": 4, "to_seq": 6}],
                "cursor_reset": False,
            }

        def unsubscribe(self, _subscriber):
            return None

    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(agent_state=State(), config={"server": {"max_stream_duration_seconds": 1}}),
    )
    handler = object.__new__(http_server.Handler)
    handler.path = "/api/agent-state/events/stream?stream_id=other&after_seq=2&timeout=0.001"
    handler.command = "GET"
    handler.headers = {"Last-Event-ID": "task%3Aone:3"}
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    handler._authorization_succeeded = True
    handler.wfile = BytesIO()
    handler.send_response = lambda _status: None
    handler.send_header = lambda _name, _value: None
    handler.end_headers = lambda: None
    handler._common_headers = lambda: None
    handler._finish_stream_request = lambda *_args, **_kwargs: None

    handler.do_GET()
    output = handler.wfile.getvalue().decode("utf-8")

    assert calls == [("task:one", 3, 1000)]
    assert "id: task%3Aone:6\nevent: retention_gap" in output
    assert "id: task%3Aone:7\nevent: task.progress" in output
    assert output.index("id: task%3Aone:6") < output.index("id: task%3Aone:7")


def test_event_stream_advances_empty_pruned_gap_from_next_seq(monkeypatch) -> None:
    event_data = AgentEvent.create("task:one", "task.progress", {"step": 7}).with_seq(7)
    calls = []
    pages = [
        {
            "success": True,
            "events": [],
            "next_seq": 6,
            "first_retained_seq": 7,
            "last_seq": 0,
            "has_more": True,
            "has_gap": True,
            "gap_ranges": [],
            "cursor_reset": False,
        },
        {
            "success": True,
            "events": [event_data],
            "next_seq": 7,
            "first_retained_seq": 7,
            "last_seq": 7,
            "has_more": False,
            "has_gap": False,
            "gap_ranges": [],
            "cursor_reset": False,
        },
    ]

    class State:
        enabled = True

        def subscribe(self, maxsize=200):
            return queue.Queue(maxsize=maxsize)

        def event_page(self, stream_id, *, after_seq, limit):
            calls.append((stream_id, after_seq, limit))
            return pages.pop(0)

        def unsubscribe(self, _subscriber):
            return None

    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(agent_state=State(), config={"server": {"max_stream_duration_seconds": 1}}),
    )
    handler, _responses = _route_handler(
        "/api/agent-state/events/stream?stream_id=task%3Aone&after_seq=2&timeout=0.001"
    )
    handler.wfile = BytesIO()
    handler.send_response = lambda _status: None
    handler.send_header = lambda _name, _value: None
    handler.end_headers = lambda: None
    handler._common_headers = lambda: None
    handler._finish_stream_request = lambda *_args, **_kwargs: None

    handler.do_GET()
    output = handler.wfile.getvalue().decode("utf-8")

    assert calls == [("task:one", 2, 1000), ("task:one", 6, 1000)]
    assert "id: task%3Aone:6\nevent: retention_gap" in output
    assert "id: task%3Aone:7\nevent: task.progress" in output
    assert output.index("id: task%3Aone:6") < output.index("id: task%3Aone:7")


def test_event_stream_fails_closed_before_sse_headers_when_page_unavailable(monkeypatch) -> None:
    error_page = {
        "success": False,
        "error": {"code": "page_read_failed", "message": "event page unavailable"},
        "terminal": False,
        "retryable": True,
    }

    class State:
        enabled = True

        def subscribe(self, maxsize=200):
            return queue.Queue(maxsize=maxsize)

        def event_page(self, _stream_id, *, after_seq, limit):
            return error_page

        def unsubscribe(self, _subscriber):
            return None

    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(agent_state=State(), config={"server": {"max_stream_duration_seconds": 1}}),
    )
    handler = object.__new__(http_server.Handler)
    handler.headers = {"Last-Event-ID": "task%3Aone:2"}
    handler.wfile = BytesIO()
    statuses = []
    headers = []
    handler.send_response = statuses.append
    handler.send_header = lambda name, value: headers.append((name, value))
    handler.end_headers = lambda: None
    handler._common_headers = lambda: None
    handler._finish_stream_request = lambda *_args, **_kwargs: None

    handler._stream_agent_events(stream_id="task:one", after_seq=2, timeout=0.001)
    body = json.loads(handler.wfile.getvalue().decode("utf-8"))

    assert statuses == [503]
    assert body == error_page
    assert ("Content-Type", "text/event-stream; charset=utf-8") not in headers
