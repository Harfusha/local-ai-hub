"""Archived T18 candidate coverage; master deliberately split the old monolith.

Paging, event-provider, and inline admin-route expectations remain candidate
contracts. They are retained for reconciliation, not verified master behavior.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlencode, urlsplit

import pytest

from local_ai_hub import http_server
from local_ai_hub.debug_traces import DebugTraceStore
from local_ai_hub.telemetry import TelemetryStore


_EVENT_TEST_ROOT = str(Path(__file__).resolve().parents[1])
_EVENT_TEST_TENANT = "tenant-t18-event-test"


def _install_event_route_app(monkeypatch, agent_state, extra_config=None):
    task_ids = ("one", "task-1")
    agent_tasks = {
        task_id: SimpleNamespace(
            context=SimpleNamespace(
                repository_id=_EVENT_TEST_ROOT,
                session_id=_EVENT_TEST_TENANT,
            )
        )
        for task_id in task_ids
    }
    config = {"security": {"api_token_tenant": _EVENT_TEST_TENANT}}
    config.update(extra_config or {})
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            agent_state=agent_state,
            agent_tasks=agent_tasks,
            config=config,
            logger=SimpleNamespace(
                warning=lambda *args, **kwargs: None,
                exception=lambda *args, **kwargs: None,
            ),
        ),
    )


def _prepare_event_route(handler, path):
    parsed = urlsplit(path)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(root=_EVENT_TEST_ROOT, tenant=_EVENT_TEST_TENANT)
    handler.path = f"{parsed.path}?{urlencode(query)}"
    if not hasattr(handler, "headers"):
        handler.headers = {}


def test_telemetry_timeline_is_recent_and_cursor_pages_older_rows(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.01)
    try:
        actions = ["/slow", "/median", "/median", "/slow", "/median"]
        for action in actions:
            store.record_http(action=action, success=True)
        assert store.flush(10)

        recent = store.get_timeline_page(limit=2)
        older = store.get_timeline_page(limit=2, before_id=recent["next_cursor"])

        assert [row["action"] for row in recent["timeline"]] == ["/slow", "/median"]
        assert recent["has_more"] is True
        assert [row["action"] for row in older["timeline"]] == ["/median", "/median"]
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


def test_telemetry_report_caps_high_cardinality_groups(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.01)
    try:
        for index in range(130):
            store.record(event_type="http", agent=f"agent-{index}", success=True)
            store.record(event_type="inference", model=f"model-{index}", success=True)
            store.record(event_type="inference", cache_layer=f"cache-{index}", success=True)
            store.record(event_type="http", error_type=f"error-{index}", success=False)
            store.record_stage(stage="cache_decision", error_type=f"decision-{index}", success=True)
            store.record(event_type="tool_accounting", input_savings_source=f"source-{index}", gross_input_tokens_avoided=1)
        store.flush(2.0)
        report = store.report(days=1)
        assert len(report["by_agent"]) <= 100
        assert len(report["by_model"]) <= 100
        assert len(report["cache_layers"]) <= 100
        assert len(report["cache_decisions"]) <= 100
        assert [(-row["requests"], row["agent"]) for row in report["by_agent"]] == sorted(
            (-row["requests"], row["agent"]) for row in report["by_agent"]
        )
        assert [(-row["calls"], row["model"]) for row in report["by_model"]] == sorted(
            (-row["calls"], row["model"]) for row in report["by_model"]
        )
        assert [row["layer"] for row in report["cache_layers"]][1:] == sorted(row["layer"] for row in report["cache_layers"][1:])
        assert list(report["cache_decisions"]) == sorted(report["cache_decisions"])
        summary = store.summary(days=1)
        assert len(summary["cache_layers"]) <= 100
        assert len(summary["http_outcomes"]) <= 100
        assert len(summary["token_savings_breakdown"]) <= 100
        cache_keys = list(summary["cache_layers"])
        outcome_keys = list(summary["http_outcomes"])
        assert cache_keys[1:] == sorted(cache_keys[1:])
        assert outcome_keys[1:] == sorted(outcome_keys[1:])
        source_keys = list(summary["token_savings_breakdown"])
        assert source_keys == sorted(source_keys)
    finally:
        store.close()


def test_dashboard_report_cache_bounds_untrusted_windows(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        for days in range(1, 80):
            store.dashboard_report(days=days, ttl_seconds=3600)
        assert len(store._dashboard_cache) <= 16
        assert all(1 <= key[0] <= 3650 for key in store._dashboard_cache)
    finally:
        store.close()


def test_summary_cache_bounds_untrusted_windows(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        for days in range(1, 80):
            store.summary(days=days, _flush=False)
        assert len(store._summary_cache) <= 16
        assert all(1 <= (key if isinstance(key, int) else key[0]) <= 3650 for key in store._summary_cache)
    finally:
        store.close()


def test_event_page_reports_empty_retention_gap_and_future_cursor(tmp_path):
    import time

    from local_ai_hub.agent_events import AgentEvent, AgentStateStore

    stream_id = 'task:empty-retention'
    state_path = tmp_path / 'agent_state.sqlite3'
    store = AgentStateStore(state_path)
    expired_at = time.time() - 60 * 86400
    for seq in range(1, 4):
        result = store.append(
            AgentEvent.create(
                stream_id,
                'task.progress',
                {'step': seq},
                idempotency_key=f'event-{seq}',
                created_at=expired_at + seq,
            )
        )
        assert result.seq == seq

    assert store.snapshot(stream_id, {'step': 3}, seq=3)
    cleanup = store.cleanup(retention_days=30)
    assert cleanup['deleted_events'] == 3

    retention_page = store.event_page(stream_id, after_seq=0, limit=10)
    assert retention_page['events'] == []
    assert retention_page['last_seq'] == 3
    assert retention_page['next_seq'] == 3
    assert retention_page['gap_ranges'] == [{'from_seq': 1, 'to_seq': 3}]
    assert retention_page['cursor_reset'] is False

    future_page = store.event_page(stream_id, after_seq=99, limit=10)
    assert future_page['events'] == []
    assert future_page['next_seq'] == 3
    assert future_page['gap_ranges'] == []
    assert future_page['cursor_reset'] is True


def test_agent_event_list_route_returns_canonical_page_and_retention_gaps(monkeypatch):
    event = {"event_id": "event-6", "stream_id": "task:task-1", "kind": "task.progress", "seq": 6}
    page = {
        "success": True,
        "events": [event],
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
        events=lambda **kwargs: pytest.fail("legacy event list bypassed event_page"),
    )
    _install_event_route_app(monkeypatch, state)
    handler = http_server.Handler.__new__(http_server.Handler)
    _prepare_event_route(handler, "/api/agent-state/events?stream_id=task:task-1&after_seq=2&limit=37")
    handler.command = "GET"
    handler._begin_trace = lambda path: None
    handler._require_authorized = lambda: True
    handler._authorization_succeeded = True
    responses = []
    handler._send = lambda status, data: responses.append((status, data))

    handler.do_GET()

    assert calls == [("task:task-1", 2, 37)]
    assert responses[0][0] == 200
    assert responses[0][1]["events"] == [event]
    assert responses[0][1]["next_seq"] == 6
    assert responses[0][1]["gap_ranges"] == [{"from_seq": 3, "to_seq": 3}]
    assert set(responses[0][1]) == set(page)


@pytest.mark.parametrize("page_reader", ["missing", "raises"])
def test_agent_event_list_route_fails_closed_without_usable_event_page(monkeypatch, page_reader):
    legacy_calls = []
    state = SimpleNamespace(
        enabled=True,
        event_page=None,
        events=lambda **kwargs: legacy_calls.append(kwargs) or [],
    )
    if page_reader == "raises":
        def event_page(*args, **kwargs):
            raise RuntimeError("page read failed")

        state.event_page = event_page
    _install_event_route_app(monkeypatch, state)
    handler = http_server.Handler.__new__(http_server.Handler)
    _prepare_event_route(handler, "/api/agent-state/events?stream_id=task:task-1&after_seq=1&limit=2")
    handler.command = "GET"
    handler._begin_trace = lambda path: None
    handler._require_authorized = lambda: True
    handler._authorization_succeeded = True
    responses = []
    handler._send = lambda status, data: responses.append((status, data))

    handler.do_GET()

    assert responses[0][0] == 503
    assert legacy_calls == []


def test_agent_event_list_route_preserves_canonical_gap_ranges(monkeypatch):
    event = {"event_id": "event-4", "stream_id": "task:task-1", "kind": "task.progress", "seq": 4}
    page = {
        "success": True,
        "events": [event],
        "next_seq": 4,
        "last_seq": 8,
        "first_retained_seq": 4,
        "gap_ranges": [{"from_seq": 3, "to_seq": 3}],
        "has_more": True,
        "cursor_reset": False,
    }
    state = SimpleNamespace(enabled=True, event_page=lambda *args, **kwargs: page)
    _install_event_route_app(monkeypatch, state)
    handler = http_server.Handler.__new__(http_server.Handler)
    _prepare_event_route(handler, "/api/agent-state/events?stream_id=task:task-1&after_seq=2")
    handler.command = "GET"
    handler._begin_trace = lambda path: None
    handler._require_authorized = lambda: True
    handler._authorization_succeeded = True
    responses = []
    handler._send = lambda status, data: responses.append((status, data))

    handler.do_GET()

    assert responses[0][0] == 200
    assert responses[0][1]["events"] == [event]
    assert responses[0][1]["next_seq"] == 4
    assert responses[0][1]["gap_ranges"] == [{"from_seq": 3, "to_seq": 3}]


def test_agent_event_sse_uses_numeric_last_event_id_with_explicit_stream_filter(monkeypatch):
    import io
    import queue
    from local_ai_hub.agent_events import AgentEvent

    event = AgentEvent.create("task:one", "task.progress", {"step": 7}).with_seq(7)
    calls = []

    class State:
        enabled = True

        def subscribe(self, maxsize=200):
            return queue.Queue(maxsize=maxsize)

        def event_page(self, stream_id, *, after_seq, limit, through_seq=None):
            calls.append((stream_id, after_seq, limit))
            return {
                "success": True,
                "events": [event],
                "next_seq": 7,
                "first_retained_seq": 7,
                "last_seq": 7,
                "has_more": False,
                "gap_ranges": [],
                "cursor_reset": False,
            }

        def unsubscribe(self, subscriber):
            return None

    _install_event_route_app(monkeypatch, State(), {"server": {"max_stream_duration_seconds": 1}})
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.headers = {"Last-Event-ID": "6"}
    _prepare_event_route(handler, "/api/agent-state/events/stream?stream_id=task:one&after_seq=2&timeout=0.01")
    handler.command = "GET"
    handler._begin_trace = lambda path: None
    handler._require_authorized = lambda: True
    handler._authorization_succeeded = True
    handler.wfile = io.BytesIO()
    handler.send_response = lambda status: None
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None
    handler._common_headers = lambda: None
    handler._finish_stream_request = lambda *args, **kwargs: None

    handler.do_GET()
    output = handler.wfile.getvalue().decode("utf-8")

    assert calls == [("task:one", 6, 100)]
    assert "id: 7" in output


def test_agent_event_sse_route_forwards_saved_cursor_query(monkeypatch):
    _install_event_route_app(monkeypatch, SimpleNamespace(enabled=True))
    handler = http_server.Handler.__new__(http_server.Handler)
    _prepare_event_route(handler, "/api/agent-state/events/stream?stream_id=task:one&after_seq=2&last_event_id=7")
    handler.command = "GET"
    handler.headers = {}
    handler._begin_trace = lambda path: None
    handler._require_authorized = lambda: True
    handler._authorization_succeeded = True
    calls = []
    handler._stream_agent_events = lambda **kwargs: calls.append(kwargs)

    handler.do_GET()

    assert calls == [{
        "stream_id": "task:one",
        "kind": "",
        "after_seq": 2,
        "timeout": 0.0,
        "last_event_id": "7",
    }]


def test_agent_event_sse_prefers_header_and_pages_replay_with_gap_metadata(monkeypatch):
    import io
    import queue
    from local_ai_hub.agent_events import AgentEvent

    first = AgentEvent.create("task:one", "task.progress", {"step": 7}).with_seq(7)
    second = AgentEvent.create("task:one", "task.progress", {"step": 8}).with_seq(8)
    calls = []
    pages = [
        {
            "success": True,
            "events": [first.to_dict()],
            "next_seq": 7,
            "gap_ranges": [{"from_seq": 4, "to_seq": 6}],
            "first_retained_seq": 7,
            "last_seq": 8,
            "has_more": True,
            "cursor_reset": False,
        },
        {
            "success": True,
            "events": [second.to_dict()],
            "next_seq": 8,
            "gap_ranges": [],
            "first_retained_seq": 7,
            "last_seq": 8,
            "has_more": False,
            "cursor_reset": False,
        },
    ]

    class State:
        enabled = True

        def subscribe(self, maxsize=200):
            return queue.Queue(maxsize=maxsize)

        def event_page(self, stream_id, *, after_seq, limit, through_seq=None):
            calls.append((stream_id, after_seq, limit))
            return pages.pop(0)

        def unsubscribe(self, subscriber):
            return None

    _install_event_route_app(monkeypatch, State(), {"server": {"max_stream_duration_seconds": 1}})
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.headers = {"Last-Event-ID": "3"}
    _prepare_event_route(handler, "/api/agent-state/events/stream?stream_id=task%3Aone&after_seq=2&timeout=0.1")
    handler.command = "GET"
    handler._begin_trace = lambda path: None
    handler._require_authorized = lambda: True
    handler._authorization_succeeded = True
    handler.wfile = io.BytesIO()
    handler.send_response = lambda status: None
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None
    handler._common_headers = lambda: None
    handler._finish_stream_request = lambda *args, **kwargs: None

    handler.do_GET()
    output = handler.wfile.getvalue().decode("utf-8")

    assert calls == [("task:one", 3, 100), ("task:one", 7, 100)]
    assert "id: 7\nevent: task.progress" in output
    assert "id: 8\nevent: task.progress" in output
    assert "event: stream.gap" in output
    assert '"from_seq":4,"to_seq":6' in output


def test_agent_event_sse_merges_events_and_internal_gaps_in_sequence_order(monkeypatch):
    import io
    import queue
    from local_ai_hub.agent_events import AgentEvent

    first = AgentEvent.create("task:one", "task.progress", {"step": 1}).with_seq(1)
    middle = AgentEvent.create("task:one", "task.progress", {"step": 3}).with_seq(3)
    last = AgentEvent.create("task:one", "task.progress", {"step": 5}).with_seq(5)

    class State:
        enabled = True

        def subscribe(self, maxsize=200):
            return queue.Queue(maxsize=maxsize)

        def event_page(self, stream_id, *, after_seq, limit, through_seq=None):
            return {
                "success": True,
                "events": [first.to_dict(), middle.to_dict(), last.to_dict()],
                "next_seq": 5,
                "first_retained_seq": 1,
                "last_seq": 5,
                "has_more": False,
                "gap_ranges": [
                    {"from_seq": 2, "to_seq": 2},
                    {"from_seq": 4, "to_seq": 4},
                ],
                "cursor_reset": False,
            }

        def unsubscribe(self, subscriber):
            return None

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(agent_state=State(), config={"server": {"max_stream_duration_seconds": 1}}))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.headers = {"Last-Event-ID": "0"}
    handler.wfile = io.BytesIO()
    handler.send_response = lambda status: None
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None
    handler._common_headers = lambda: None
    handler._finish_stream_request = lambda *args, **kwargs: None

    handler._stream_agent_events(stream_id="task:one", after_seq=0, timeout=0.001)
    output = handler.wfile.getvalue().decode("utf-8")

    positions = [
        output.index("id: 1\n"),
        output.index("id: 2\n"),
        output.index("id: 3\n"),
        output.index("id: 4\n"),
        output.index("id: 5\n"),
    ]
    assert positions == sorted(positions)
    ids = [line.removeprefix("id: ") for line in output.splitlines() if line.startswith("id: ")]
    assert ids == [str(seq) for seq in range(1, 6)]
    assert output.count("event: stream.gap") == 2
    assert '"from_seq":2,"to_seq":2' in output
    assert '"from_seq":4,"to_seq":4' in output


def test_agent_event_sse_paginates_filtered_replay_with_canonical_pages(monkeypatch):
    import io
    import queue
    from local_ai_hub.agent_events import AgentEvent

    events = [AgentEvent.create("task:one", "task.progress", {"step": seq}).with_seq(seq) for seq in range(1, 1002)]
    calls = []

    class State:
        enabled = True

        def subscribe(self, maxsize=200):
            return queue.Queue(maxsize=maxsize)

        def event_page(self, stream_id, *, after_seq, limit, through_seq=None):
            calls.append((after_seq, limit))
            page_events = [event for event in events if event.seq > after_seq][:limit]
            return {
                "success": True,
                "events": [event.to_dict() for event in page_events],
                "next_seq": page_events[-1].seq if page_events else after_seq,
                "first_retained_seq": 1,
                "last_seq": events[-1].seq,
                "has_more": any(event.seq > (page_events[-1].seq if page_events else after_seq) for event in events),
                "gap_ranges": [],
                "cursor_reset": False,
            }

        def unsubscribe(self, subscriber):
            return None

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(agent_state=State(), config={"server": {"max_stream_duration_seconds": 1}}))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.headers = {"Last-Event-ID": "task%3Aone:0"}
    handler.wfile = io.BytesIO()
    handler.send_response = lambda status: None
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None
    handler._common_headers = lambda: None
    handler._finish_stream_request = lambda *args, **kwargs: None

    handler._stream_agent_events(stream_id="task:one", kind="task.done", after_seq=0, timeout=1.0)
    output = handler.wfile.getvalue().decode("utf-8")

    assert calls == [(cursor, 100) for cursor in range(0, 1001, 100)]
    assert "event: task.progress" not in output
    assert "id: 1001\nevent: replay_page" in output
    assert "event: stream_timeout" in output
    assert '"last_seq":1001' in output


@pytest.mark.parametrize("page_reader", ["missing", "raises"])
def test_agent_event_sse_fails_closed_without_usable_event_page(monkeypatch, page_reader):
    import io
    import queue

    legacy_calls = []

    class State:
        enabled = True

        def subscribe(self, maxsize=200):
            return queue.Queue(maxsize=maxsize)

        def events(self, **kwargs):
            legacy_calls.append(kwargs)
            return []

        def unsubscribe(self, subscriber):
            return None

    if page_reader == "raises":
        def event_page(*args, **kwargs):
            raise RuntimeError("page read failed")

        State.event_page = event_page

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(agent_state=State(), config={"server": {"max_stream_duration_seconds": 1}}))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.headers = {"Last-Event-ID": "task%3Aone:2"}
    handler.wfile = io.BytesIO()
    statuses = []
    handler.send_response = statuses.append
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None
    handler._common_headers = lambda: None
    handler._finish_stream_request = lambda *args, **kwargs: None

    handler._stream_agent_events(stream_id="task:one", after_seq=2, timeout=0.001)
    response_body = json.loads(handler.wfile.getvalue().decode("utf-8"))

    assert statuses == [503]
    assert response_body == {
        "success": False,
        "error": {"code": "event_page_unavailable", "message": "Event page could not be read."},
        "next_seq": 2,
        "terminal": False,
        "retryable": True,
    }
    assert legacy_calls == []


def test_agent_event_sse_preserves_initial_provider_failure_before_headers(monkeypatch):
    import io
    import queue

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

        def event_page(self, stream_id, *, after_seq, limit):
            return error_page

        def unsubscribe(self, subscriber):
            return None

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(agent_state=State(), config={"server": {"max_stream_duration_seconds": 1}}))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.headers = {"Last-Event-ID": "task%3Aone:2"}
    handler.wfile = io.BytesIO()
    statuses = []
    headers = []
    handler.send_response = statuses.append
    handler.send_header = lambda name, value: headers.append((name, value))
    handler.end_headers = lambda: None
    handler._common_headers = lambda: None
    handler._finish_stream_request = lambda *args, **kwargs: None

    handler._stream_agent_events(stream_id="task:one", after_seq=2, timeout=0.001)
    response_body = json.loads(handler.wfile.getvalue().decode("utf-8"))

    assert statuses == [503]
    assert response_body == error_page
    assert ("Content-Type", "text/event-stream") not in headers


def test_agent_event_sse_emits_later_provider_failure_after_headers(monkeypatch):
    import io
    import queue

    calls = []
    error_page = {
        "success": False,
        "error": {"code": "later_page_failed", "message": "event page unavailable"},
        "terminal": False,
        "retryable": True,
    }

    class State:
        enabled = True

        def subscribe(self, maxsize=200):
            return queue.Queue(maxsize=maxsize)

        def event_page(self, stream_id, *, after_seq, limit):
            calls.append(after_seq)
            if len(calls) == 1:
                return {
                    "success": True,
                    "events": [],
                    "next_seq": 1,
                    "first_retained_seq": 1,
                    "last_seq": 1,
                    "has_more": True,
                    "gap_ranges": [],
                    "cursor_reset": False,
                }
            return error_page

        def unsubscribe(self, subscriber):
            return None

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(agent_state=State(), config={"server": {"max_stream_duration_seconds": 1}}))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.headers = {"Last-Event-ID": "task%3Aone:0"}
    handler.wfile = io.BytesIO()
    statuses = []
    handler.send_response = statuses.append
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None
    handler._common_headers = lambda: None
    handler._finish_stream_request = lambda *args, **kwargs: None

    handler._stream_agent_events(stream_id="task:one", after_seq=0, timeout=1.0)
    output = handler.wfile.getvalue().decode("utf-8")

    assert calls == [0, 1]
    assert statuses == [200]
    assert "event: replay_error\ndata: {\"success\":false,\"error\":{\"code\":\"later_page_failed\",\"message\":\"event page unavailable\"},\"terminal\":false,\"retryable\":true}" in output


def test_agent_event_sse_empty_retention_gap_advances_reconnect_cursor(monkeypatch):
    import io
    import queue

    calls = []

    class State:
        enabled = True

        def subscribe(self, maxsize=200):
            return queue.Queue(maxsize=maxsize)

        def event_page(self, stream_id, *, after_seq, limit):
            calls.append(after_seq)
            return {
                "success": True,
                "events": [],
                "next_seq": 5,
                "first_retained_seq": 6,
                "last_seq": 6,
                "gap_ranges": [{"from_seq": 3, "to_seq": 5}],
                "has_more": False,
                "cursor_reset": False,
            }

        def unsubscribe(self, subscriber):
            return None

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(agent_state=State(), config={"server": {"max_stream_duration_seconds": 1}}))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.headers = {"Last-Event-ID": "task%3Aone:2"}
    handler.wfile = io.BytesIO()
    handler.send_response = lambda status: None
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None
    handler._common_headers = lambda: None
    handler._finish_stream_request = lambda *args, **kwargs: None

    handler._stream_agent_events(stream_id="task:one", after_seq=2, timeout=0.001)
    output = handler.wfile.getvalue().decode("utf-8")

    assert calls == [2]
    assert "event: retention_gap" in output
    assert "id: task%3Aone:5\nevent: retention_gap\n" in output
    assert '"next_seq":5' in output


def test_agent_event_sse_reports_cursor_reset_and_rewinds_future_cursor(monkeypatch):
    import io
    import queue

    calls = []

    class State:
        enabled = True

        def subscribe(self, maxsize=200):
            return queue.Queue(maxsize=maxsize)

        def event_page(self, stream_id, *, after_seq, limit):
            calls.append(after_seq)
            return {
                "success": True,
                "events": [],
                "next_seq": 5,
                "first_retained_seq": 6,
                "last_seq": 8,
                "has_more": False,
                "gap_ranges": [],
                "cursor_reset": True,
            }

        def unsubscribe(self, subscriber):
            return None

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(agent_state=State(), config={"server": {"max_stream_duration_seconds": 1}}))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.headers = {"Last-Event-ID": "task%3Aone:99"}
    handler.wfile = io.BytesIO()
    handler.send_response = lambda status: None
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None
    handler._common_headers = lambda: None
    handler._finish_stream_request = lambda *args, **kwargs: None

    handler._stream_agent_events(stream_id="task:one", after_seq=99, timeout=0.001)
    output = handler.wfile.getvalue().decode("utf-8")

    assert calls == [99]
    assert "event: cursor_reset" in output
    assert "id: task%3Aone:5\nevent: cursor_reset\n" in output


def test_agent_event_list_route_preserves_provider_page_failure(monkeypatch):
    error_page = {
        "success": False,
        "error": {"code": "page_read_failed", "message": "event page unavailable"},
        "terminal": False,
        "retryable": True,
    }
    state = SimpleNamespace(enabled=True, event_page=lambda *args, **kwargs: error_page)
    _install_event_route_app(monkeypatch, state)
    handler = http_server.Handler.__new__(http_server.Handler)
    _prepare_event_route(handler, "/api/agent-state/events?stream_id=task:task-1&after_seq=2")
    handler.command = "GET"
    handler._begin_trace = lambda path: None
    handler._require_authorized = lambda: True
    handler._authorization_succeeded = True
    responses = []
    handler._send = lambda status, data: responses.append((status, data))

    handler.do_GET()

    assert responses == [(503, error_page)]


def test_agent_event_sse_filtered_cursor_reconnect_delivers_next_matching_event(monkeypatch):
    import io
    import queue
    from local_ai_hub.agent_events import AgentEvent

    events = [
        AgentEvent.create("task:one", "task.progress", {"step": 1}).with_seq(1),
        AgentEvent.create("task:one", "task.done", {"step": 2}).with_seq(2),
    ]
    calls = []

    class State:
        enabled = True

        def subscribe(self, maxsize=200):
            return queue.Queue(maxsize=maxsize)

        def event_page(self, stream_id, *, after_seq, limit):
            calls.append(after_seq)
            page_events = [event for event in events if event.seq > after_seq][:limit]
            return {
                "success": True,
                "events": page_events,
                "next_seq": page_events[-1].seq if page_events else after_seq,
                "first_retained_seq": 1,
                "last_seq": max(event.seq for event in events),
                "has_more": False,
                "gap_ranges": [],
                "cursor_reset": False,
            }

        def unsubscribe(self, subscriber):
            return None

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(agent_state=State(), config={"server": {"max_stream_duration_seconds": 1}}))

    def stream(last_event_id):
        handler = http_server.Handler.__new__(http_server.Handler)
        handler.headers = {"Last-Event-ID": last_event_id}
        handler.wfile = io.BytesIO()
        handler.send_response = lambda status: None
        handler.send_header = lambda name, value: None
        handler.end_headers = lambda: None
        handler._common_headers = lambda: None
        handler._finish_stream_request = lambda *args, **kwargs: None
        after_seq = int(last_event_id.rpartition(":")[2])
        handler._stream_agent_events(stream_id="task:one", kind="task.done", after_seq=after_seq, timeout=0.001)
        return handler.wfile.getvalue().decode("utf-8")

    first = stream("task%3Aone:0")
    events.append(AgentEvent.create("task:one", "task.done", {"step": 3}).with_seq(3))
    second = stream("task%3Aone:2")

    assert calls == [0, 2]
    assert "event: task.progress" not in first
    assert "event: task.done" in first and '"step":2' in first
    assert '"step":3' not in first
    assert "event: task.done" in second and '"step":3' in second
    assert '"step":1' not in second and '"step":2' not in second


def test_agent_event_sse_live_filter_advances_cursor_without_emitting_other_kind(monkeypatch):
    import io
    import queue
    from local_ai_hub.agent_events import AgentEvent

    subscriber = queue.Queue()
    subscriber.put(AgentEvent.create("task:one", "task.progress", {"step": 2}).with_seq(2))

    class State:
        enabled = True

        def subscribe(self, maxsize=200):
            return subscriber

        def event_page(self, stream_id, *, after_seq, limit):
            return {
                "success": True,
                "events": [],
                "next_seq": after_seq,
                "first_retained_seq": 1,
                "last_seq": 1,
                "has_more": False,
                "gap_ranges": [],
                "cursor_reset": False,
            }

        def unsubscribe(self, subscriber):
            return None

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(agent_state=State(), config={"server": {"max_stream_duration_seconds": 1}}))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.headers = {"Last-Event-ID": "task%3Aone:1"}
    handler.wfile = io.BytesIO()
    handler.send_response = lambda status: None
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None
    handler._common_headers = lambda: None
    handler._finish_stream_request = lambda *args, **kwargs: None

    handler._stream_agent_events(stream_id="task:one", kind="task.done", after_seq=1, timeout=0.01)
    output = handler.wfile.getvalue().decode("utf-8")

    assert "id: task%3Aone:2" in output
    assert "event: task.progress" not in output
    assert '"last_seq":2' in output


def test_trace_detail_is_paginated_and_response_bytes_are_capped(tmp_path):
    store = DebugTraceStore({
        "server": {"state_dir": str(tmp_path)},
        "debug_traces": {
            "enabled": True,
            "max_event_bytes": 8192,
            "max_detail_response_bytes": 16384,
        },
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


def test_debug_trace_list_retryable_store_failure_returns_503(monkeypatch):
    failure = {"success": False, "error": "trace store unavailable", "retryable": True}
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(debug_traces=SimpleNamespace(list=lambda **kwargs: failure)))

    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/debug-traces"
    handler.command = "GET"
    handler._begin_trace = lambda path: None
    handler._require_authorized = lambda: True
    handler._authorization_succeeded = True
    handler._authorize_admin_action = lambda action: action == "debug_traces.list"
    handler._reconcile_debug_trace = lambda item: item
    responses = []
    handler._send = lambda status, data: responses.append((status, data))

    handler.do_GET()

    assert responses == [(503, failure)]


def test_agent_state_detail_reports_degraded_status_on_dependency_timeout(monkeypatch):
    monkeypatch.setattr(http_server, "_STATUS_DEPENDENCY_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            _status_dependency_lock=threading.Lock(),
            _status_dependency_inflight={},
            _status_dependency_slots=threading.BoundedSemaphore(2),
            agent_state=SimpleNamespace(enabled=True),
            agent_tasks=SimpleNamespace(list_tasks=lambda: []),
            agent_incidents=SimpleNamespace(list_incidents=lambda: []),
            agent_learning=SimpleNamespace(list_candidates=lambda: []),
        ),
    )
    handler = object.__new__(http_server.Handler)
    handler.path = "/api/status?detail=agent_state"
    handler.command = "GET"
    handler._authorization_root = "C:/project"
    handler._authorization_tenant = "owner"
    handler._begin_trace = lambda path: None
    handler._require_authorized = lambda: True
    responses = []
    handler._send = lambda status, data: responses.append((status, data))

    handler.do_GET()

    assert len(responses) == 1
    assert responses[0][1]["degraded"] is True
    assert responses[0][1]["success"] is False
    assert responses[0][1]["status"] == "degraded"


def test_agent_state_detail_includes_contract_counts(monkeypatch):
    candidate_calls = []
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            _status_dependency_lock=threading.Lock(),
            _status_dependency_inflight={},
            _status_dependency_slots=threading.BoundedSemaphore(2),
            agent_state=SimpleNamespace(enabled=True),
            agent_tasks=SimpleNamespace(
                list_tasks=lambda: [SimpleNamespace(
                    task_id="t1",
                    status=http_server.TaskStatus.ACTIVE,
                    context=SimpleNamespace(repository_id=_EVENT_TEST_ROOT, session_id="owner"),
                )]
            ),
            agent_incidents=SimpleNamespace(list_incidents=lambda: [
                SimpleNamespace(
                    repository_key=http_server._incident_scope_key("repository", _EVENT_TEST_ROOT),
                    tenant_key=http_server._incident_scope_key("tenant", "owner"),
                ),
                SimpleNamespace(
                    repository_key=http_server._incident_scope_key("repository", _EVENT_TEST_ROOT),
                    tenant_key=http_server._incident_scope_key("tenant", "owner"),
                ),
            ]),
            agent_learning=SimpleNamespace(list_candidates=lambda: candidate_calls.append(True) or [object()]),
        ),
    )
    handler = object.__new__(http_server.Handler)
    handler.path = "/api/status?detail=agent_state"
    handler.command = "GET"
    handler._authorization_root = _EVENT_TEST_ROOT
    handler._authorization_tenant = "owner"
    handler._begin_trace = lambda path: None
    handler._require_authorized = lambda: True
    responses = []
    handler._send = lambda status, data: responses.append((status, data))

    handler.do_GET()

    assert len(responses) == 1
    status, payload = responses[0]
    assert status == 200
    assert payload["success"] is True
    assert payload["enabled"] is True
    assert payload["active_tasks"] == ["t1"]
    assert payload["tasks_count"] == 1
    assert payload["incidents_count"] == 2
    assert payload["candidates_count"] == 0
    assert candidate_calls == []


def test_db_query_rejects_results_over_byte_budget(monkeypatch, tmp_path):
    db = tmp_path / "agent_state.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE payloads (payload TEXT)")
        con.executemany("INSERT INTO payloads VALUES (?)", [("x" * 3000,) for _ in range(4)])
        con.commit()
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"server": {"state_dir": str(tmp_path)}}))
    monkeypatch.setattr(http_server, "_DB_QUERY_MAX_RESPONSE_BYTES", 8192)

    result = http_server.Handler._handle_db_query(None, "agent_state", "SELECT payload FROM payloads")

    assert result == {"success": False, "error": "query result exceeded byte limit"}


def test_db_query_enforces_hard_row_cap(monkeypatch, tmp_path):
    db = tmp_path / "agent_state.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE markers (value INTEGER)")
        con.executemany("INSERT INTO markers VALUES (?)", ((value,) for value in range(1, 111)))
        con.commit()
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"server": {"state_dir": str(tmp_path)}}))
    monkeypatch.setattr(http_server, "_DB_QUERY_MAX_RESPONSE_BYTES", 64 * 1024)

    result = http_server.Handler._handle_db_query(None, "agent_state", "SELECT value FROM markers ORDER BY value")

    assert result["success"] is True
    assert result["count"] == 100
    assert result["rows"] == [[value] for value in range(1, 101)]


def test_db_query_rejects_write_and_leaves_database_unchanged(monkeypatch, tmp_path):
    db = tmp_path / "agent_state.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE marker (value INTEGER)")
        con.execute("INSERT INTO marker VALUES (1)")
        con.commit()
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"server": {"state_dir": str(tmp_path)}}))

    result = http_server.Handler._handle_db_query(None, "agent_state", "UPDATE marker SET value = 2")

    with closing(sqlite3.connect(db)) as con:
        value = con.execute("SELECT value FROM marker").fetchone()[0]
    assert result["success"] is False
    assert value == 1


def test_db_query_authorizer_denies_unapproved_sqlite_functions(monkeypatch, tmp_path):
    db = tmp_path / "agent_state.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE marker (value INTEGER)")
        con.commit()
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"server": {"state_dir": str(tmp_path)}}))

    result = http_server.Handler._handle_db_query(None, "agent_state", "SELECT load_extension('not-loaded')")

    assert result["success"] is False
    assert result["error"] == "not authorized"


def test_db_query_work_budget_returns_fail_closed_error(monkeypatch, tmp_path):
    db = tmp_path / "agent_state.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE numbers (value INTEGER NOT NULL)")
        con.executemany("INSERT INTO numbers VALUES (?)", ((value,) for value in range(300)))
        con.commit()
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"server": {"state_dir": str(tmp_path)}}))

    result = http_server.Handler._handle_db_query(
        None,
        "agent_state",
        "SELECT count(*) FROM numbers a CROSS JOIN numbers b CROSS JOIN numbers c",
    )

    assert result["success"] is False
    assert result == {"success": False, "error": "query execution exceeded work limit"}


def test_model_pull_has_total_deadline_and_closes_slow_response(monkeypatch):
    closed = threading.Event()

    class SlowResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.close()

        def read(self, size=-1):
            closed.wait(1)
            return b'{"status":"success"}'

        def close(self):
            closed.set()

    response = SlowResponse()
    monkeypatch.setattr(http_server, "_MODEL_PULL_TIMEOUT_SECONDS", 0.02, raising=False)
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(config={"ollama": {"url": "http://ollama.test"}}),
    )
    monkeypatch.setattr(http_server.urllib.request, "urlopen", lambda req, timeout: response)
    handler = object.__new__(http_server.Handler)
    started = time.monotonic()

    result = handler._handle_models_action("pull", "test-model")

    assert result["success"] is False
    assert result["retryable"] is True
    assert result["error"] == "model pull time budget exceeded"
    assert time.monotonic() - started < 0.5
    assert closed.is_set()


def test_telemetry_error_resolution_deadline_rolls_back(monkeypatch, tmp_path):
    import local_ai_hub.telemetry as telemetry_module

    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.01)
    try:
        store.record_http(action="/api/example", success=False, error_type="internal")
        assert store.flush(10)
        clock_values = iter([0.0, 0.0] + [2.0] * 20)
        with monkeypatch.context() as patcher:
            patcher.setattr(store, "flush", lambda timeout: True)
            patcher.setattr(
                telemetry_module,
                "time",
                SimpleNamespace(monotonic=lambda: next(clock_values), time=time.time),
            )
            result = store.resolve_errors(timeout_seconds=0.05)

        assert result["success"] is False
        assert result["retryable"] is True
        with closing(store._connect()) as con:
            assert con.execute("SELECT COUNT(*) FROM events WHERE success=0").fetchone()[0] == 1
    finally:
        store.close()


def test_incident_resolution_deadline_rolls_back(monkeypatch, tmp_path):
    import local_ai_hub.agent_incidents as incident_module
    from local_ai_hub.agent_events import AgentStateStore
    from local_ai_hub.agent_incidents import IncidentStore, ToolOutcome

    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store = IncidentStore(state_store)
    incident = store.capture(
        ToolOutcome(
            tool_name="command",
            command="python -m pytest",
            error="database busy",
            exit_code=1,
            state_revision="test-rev",
            evidence_ids=("ev-timeout",),
        )
    )
    assert incident is not None
    clock_values = iter([0.0, 0.0] + [2.0] * 20)
    with monkeypatch.context() as patcher:
        patcher.setattr(
            incident_module,
            "time",
            SimpleNamespace(monotonic=lambda: next(clock_values), time=time.time),
        )
        with pytest.raises(TimeoutError, match="incident resolution time budget exceeded"):
            store.resolve_all(timeout_seconds=0.05)

    assert store.list_incidents(resolved=False)


def test_incident_resolution_uses_unique_event_keys_for_each_clear(monkeypatch, tmp_path):
    import time
    from types import SimpleNamespace

    import local_ai_hub.agent_incidents as incident_module
    from local_ai_hub.agent_events import AgentStateStore
    from local_ai_hub.agent_incidents import IncidentStore, ToolOutcome

    monkeypatch.setattr(
        incident_module,
        "time",
        SimpleNamespace(monotonic=time.monotonic, time=lambda: 1_700_000_000.25),
    )
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store = IncidentStore(state_store)

    def capture(error: str) -> None:
        assert store.capture(
            ToolOutcome(
                tool_name="command",
                command="python -m pytest",
                error=error,
                exit_code=1,
                state_revision="same-second",
                evidence_ids=(f"ev-{error}",),
            )
        ) is not None

    capture("first failure")
    assert store.resolve_all() == 1
    capture("second failure")
    assert store.resolve_all() == 1

    events = [
        event for event in state_store.events("incident:all")
        if event.kind == "incident.all_resolved"
    ]
    assert len(events) == 2
    assert len({event.idempotency_key for event in events}) == 2


def test_transactional_event_append_requires_initialized_store_before_transaction(tmp_path):
    import sqlite3
    from local_ai_hub.agent_events import AgentEvent, AgentStateStore

    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    con = sqlite3.connect(store.db_path)
    try:
        con.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="schema must be initialized before opening"):
            store.append_in_transaction(con, AgentEvent.create("incident:all", "incident.all_resolved", {}))
        assert con.in_transaction
        assert not store._initialized
    finally:
        con.rollback()
        con.close()


def test_incident_resolution_does_not_report_timeout_after_commit(monkeypatch, tmp_path):
    import local_ai_hub.agent_incidents as incident_module
    from local_ai_hub.agent_events import AgentStateStore
    from local_ai_hub.agent_incidents import IncidentStore, ToolOutcome

    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store = IncidentStore(state_store)
    incident = store.capture(
        ToolOutcome(
            tool_name="command",
            command="python -m pytest",
            error="database busy",
            exit_code=1,
            state_revision="test-rev",
            evidence_ids=("ev-post-commit-timeout",),
        )
    )
    assert incident is not None

    clock = {"now": 0.0}
    monkeypatch.setattr(
        incident_module,
        "time",
        SimpleNamespace(monotonic=lambda: clock["now"], time=time.time),
    )
    connect_sqlite = incident_module.connect_sqlite

    class CommitClockConnection:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            result = self.connection.__exit__(*args)
            if args[0] is None:
                clock["now"] = 2.0
            return result

    monkeypatch.setattr(
        incident_module,
        "connect_sqlite",
        lambda *args, **kwargs: CommitClockConnection(connect_sqlite(*args, **kwargs)),
    )
    published = []
    monkeypatch.setattr(
        state_store,
        "append_in_transaction",
        lambda con, event: SimpleNamespace(retryable=False, error=None, duplicate=False, event=event),
        raising=False,
    )

    def publish_then_fail(event):
        published.append(event)
        raise RuntimeError("subscriber wake failed")

    monkeypatch.setattr(state_store, "_publish", publish_then_fail)

    assert store.resolve_all(timeout_seconds=1.0) == 1
    assert store.list_incidents(resolved=False) == []
    assert [event.kind for event in published] == ["incident.all_resolved"]


def test_incident_resolution_rolls_back_when_audit_event_cannot_append(tmp_path, monkeypatch):
    from local_ai_hub.agent_events import AgentStateStore
    from local_ai_hub.agent_incidents import IncidentStore, ToolOutcome

    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store = IncidentStore(state_store)
    incident = store.capture(
        ToolOutcome(
            tool_name="command",
            command="python -m pytest",
            error="database busy",
            exit_code=1,
            state_revision="test-rev",
            evidence_ids=("ev-audit-timeout",),
        )
    )
    assert incident is not None
    monkeypatch.setattr(
        state_store,
        "append_in_transaction",
        lambda con, event: SimpleNamespace(retryable=True, error="database busy"),
        raising=False,
    )

    with pytest.raises(TimeoutError, match="incident resolution time budget exceeded"):
        store.resolve_all(timeout_seconds=0.05)

    assert store.list_incidents(resolved=False)
    with closing(sqlite3.connect(state_store.db_path)) as con:
        assert con.execute("SELECT COUNT(*) FROM agent_events WHERE kind='incident.all_resolved'").fetchone()[0] == 0


def test_resolve_all_errors_propagates_retryable_store_deadlines(tmp_path):
    from local_ai_hub.services import LocalAIServices

    class TimedOutTelemetry:
        def resolve_errors(self, *, timeout_seconds):
            assert 0 < timeout_seconds <= 0.05
            return {"success": False, "degraded": True, "retryable": True}

    class TimedOutIncidents:
        def resolve_all(self, *, verified_fix, root_cause, timeout_seconds):
            assert verified_fix == "Resolved by operator"
            assert root_cause == "Operator manual resolve"
            assert 0 < timeout_seconds <= 0.05
            raise TimeoutError("incident resolution time budget exceeded")

    service = object.__new__(LocalAIServices)
    service.config = {"server": {"state_dir": str(tmp_path)}}
    service.telemetry = TimedOutTelemetry()
    service.incident_store = TimedOutIncidents()

    result = service.resolve_all_errors(timeout_seconds=0.05)

    assert result["success"] is False
    assert result["degraded"] is True
    assert result["retryable"] is True


def test_resolve_all_errors_shares_one_deadline_across_stores(tmp_path, monkeypatch):
    import local_ai_hub.services as services_module
    from local_ai_hub.services import LocalAIServices

    clock = {"now": 0.0}
    captured = {}

    class Telemetry:
        def resolve_errors(self, *, timeout_seconds):
            captured["telemetry"] = timeout_seconds
            clock["now"] = 0.03
            return {"success": True}

    class Incidents:
        def resolve_all(self, *, verified_fix, root_cause, timeout_seconds):
            captured["incidents"] = timeout_seconds
            return 0

    service = object.__new__(LocalAIServices)
    service.config = {"server": {"state_dir": str(tmp_path)}}
    service.telemetry = Telemetry()
    service.incident_store = Incidents()
    monkeypatch.setattr(services_module, "time", SimpleNamespace(monotonic=lambda: clock["now"]))

    result = service.resolve_all_errors(timeout_seconds=0.05)

    assert captured["telemetry"] == pytest.approx(0.05)
    assert captured["incidents"] == pytest.approx(0.02)
    assert result["success"] is True


def test_admin_action_policy_rejects_wrong_method_and_audits_metadata_only(monkeypatch):
    handler = object.__new__(http_server.Handler)
    handler.command = "GET"
    handler.path = "/api/maintenance/optimize_db"
    handler._authorization_succeeded = True
    sent = []
    handler._send = lambda status, body, **kwargs: sent.append((status, body, kwargs.get("headers", {})))

    assert handler._authorize_admin_action("maintenance.optimize_db") is False
    assert sent[0][0] == 405
    assert sent[0][2] == {"Allow": "POST"}

    audits = []
    def record_system(action, **event):
        audits.append((action, event))
        return True

    telemetry = SimpleNamespace(record_system=record_system)
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(telemetry=telemetry))
    handler._admin_operation = "maintenance.optimize_db"
    handler._request_started = time.perf_counter() - 0.01
    assert handler._audit_admin_action(200, {"prompt": "secret", "source_text": "private", "path": "C:\\private\\repo"}) is True

    assert audits[0][0] == "admin.maintenance.optimize_db"
    assert "prompt" not in audits[0][1]
    assert "source_text" not in audits[0][1]
    assert "path" not in audits[0][1]


def test_admin_audit_queue_rejection_is_visible_in_response(monkeypatch):
    import io
    import json

    handler = object.__new__(http_server.Handler)
    handler._admin_operation = "maintenance.optimize_db"
    handler._admin_audited = False
    handler._request_started = time.perf_counter()
    handler._telemetry_finished = True
    handler._debug_trace_finished = True
    handler._journal_request_id = None
    handler.wfile = io.BytesIO()
    handler.send_response = lambda status: None
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None
    handler._common_headers = lambda: None
    handler._finish_debug_trace = lambda *args, **kwargs: None
    handler._close_trace_context = lambda: None
    telemetry = SimpleNamespace(record_system=lambda action, **event: False)
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(telemetry=telemetry))

    handler._send(200, {"success": True, "changed": True})
    response = json.loads(handler.wfile.getvalue())

    assert response["success"] is True
    assert response["audit_accepted"] is False
    assert "may have completed" in response["warning"]
    assert handler._admin_audited is False


def test_admin_wrong_method_sends_allow_header_over_http(monkeypatch):
    import http.client
    import threading

    class AdminGuardHandler(http_server.Handler):
        def do_GET(self):
            self._authorization_succeeded = True
            self._authorize_admin_action("maintenance.optimize_db")

    monkeypatch.setattr(http_server, "APP", None)
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), AdminGuardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection(*server.server_address, timeout=2)
    try:
        connection.request("GET", "/api/maintenance/optimize_db")
        response = connection.getresponse()
        body = json.loads(response.read())

        assert response.status == 405
        assert response.getheader("Allow") == "POST"
        assert body["status_code"] == 405
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_retryable_error_resolution_returns_503_over_http(monkeypatch, tmp_path):
    import http.client
    import threading

    class Services:
        def resolve_all_errors(self):
            return {"success": False, "degraded": True, "retryable": True}

    class AdminHandler(http_server.Handler):
        def _begin_trace(self, path):
            self._telemetry_finished = True

        def _require_authorized(self):
            self._authorization_succeeded = True
            return True

    app = SimpleNamespace(
        config={"server": {}, "observability": {"exclude_http_paths": []}},
        services=Services(),
        telemetry=SimpleNamespace(record_system=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(http_server, "APP", app)
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), AdminHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection(*server.server_address, timeout=2)
    try:
        connection.request(
            "POST",
            "/api/maintenance/resolve_errors",
            body="{}",
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        body = json.loads(response.read())

        assert response.status == 503
        assert body["retryable"] is True
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize(
    ("operation", "method", "path", "payload"),
    [
        ("db.query", "GET", "/api/db/query", {}),
        ("debug_traces.list", "GET", "/api/debug-traces", {}),
        ("debug_traces.detail", "GET", "/api/debug-traces/trace-1", {}),
        ("config.read", "GET", "/api/config", {}),
        ("config.update", "POST", "/api/config/update", {"action": "update"}),
        ("config.reset", "POST", "/api/config/update", {"action": "reset"}),
        ("maintenance.optimize_db", "POST", "/api/maintenance/optimize_db", {}),
        ("maintenance.purge_cache", "POST", "/api/maintenance/purge_cache", {}),
        ("maintenance.resolve_errors", "POST", "/api/maintenance/resolve_errors", {}),
        ("models.list", "GET", "/api/models/manage", {}),
        ("models.list", "POST", "/api/models/manage", {"action": "list"}),
        ("models.pull", "POST", "/api/models/manage", {"action": "pull"}),
        ("models.delete", "POST", "/api/models/manage", {"action": "delete"}),
        ("bundle.import", "POST", "/api/bundle/import", {}),
    ],
)
def test_admin_action_policy_covers_each_t18_operation(operation, method, path, payload):
    handler = object.__new__(http_server.Handler)
    handler.command = method
    handler.path = path
    handler._authorization_succeeded = True
    handler._admin_payload = payload
    sent = []
    handler._send = lambda status, body, **kwargs: sent.append((status, body))

    assert handler._authorize_admin_action(operation) is True
    assert handler._admin_operation == operation
    assert sent == []


def test_status_action_aliases_match_live_and_generated_schemas():
    import asyncio
    from local_ai_hub import mcp_server
    from local_ai_hub.generator import generate_mcp_tool_schemas
    import mcp.types as mcp_types

    details = {"brief", "cache", "telemetry", "full", "agent_state"}
    aliases = {"status", "health", "check", "info"}
    schemas = generate_mcp_tool_schemas({})["local_ai_status"]["parameters"]["properties"]
    list_handler = mcp_server.mcp._mcp_server.request_handlers[mcp_types.ListToolsRequest]
    response = asyncio.run(list_handler(mcp_types.ListToolsRequest(method="tools/list")))
    wire_tool = next(tool for tool in response.root.tools if tool.name == "local_ai_status")
    live = wire_tool.inputSchema["properties"]

    assert set(live["detail"]["enum"]) == details
    assert set(schemas["detail"]["enum"]) == details
    assert live["action"].get("enum") == schemas["action"]["enum"]
    assert (details | aliases) <= set(live["action"].get("enum", []))


def test_status_action_aliases_route_to_expected_live_status_scope(monkeypatch):
    from local_ai_hub import mcp_server

    aliases = {"status", "health", "check", "info"}
    calls = []
    status = {"success": True, "hub_online": True, "version": "test", "scheduler": {}, "observability": {}, "runtime_stats": {}}

    class Client:
        def get(self, path):
            calls.append(path)
            if path == "/api/capabilities":
                return {"capabilities": []}
            if path.startswith("/api/telemetry/report"):
                return {"success": True, "summary": {}}
            return dict(status)

        def status(self, **kwargs):
            calls.append(("status", kwargs))
            return status

    monkeypatch.setattr(mcp_server, "CLIENT", Client())
    monkeypatch.setattr(mcp_server, "FEATURES", SimpleNamespace(status=True, tasks=False, has_any_model=lambda: False))
    expected_calls = {
        **{alias: ["/api/live/status?light=1&scope=process"] for alias in aliases},
        "brief": ["/api/live/status?light=1&scope=process"],
        "cache": ["/api/live/status?light=1&scope=process"],
        "telemetry": ["/api/telemetry/report?days=30&scope=process"],
        "full": ["/api/live/status?light=1&scope=process", "/api/capabilities"],
        "agent_state": [("status", {"detail": "agent_state"})],
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


def test_pubsub_polls_durable_sequence_pages_and_reports_retention_gap(tmp_path):
    from local_ai_hub.agent_events import AgentStateStore, SwarmPubSub

    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    bus = SwarmPubSub(state_store=state_store)
    for index in range(3):
        result = bus.publish("build", {"index": index}, sender="worker")
        assert result["success"] is True

    with closing(sqlite3.connect(db_path)) as con:
        con.execute("DELETE FROM agent_events WHERE stream_id=? AND seq=1", ("pubsub:build",))
        con.commit()

    first_page = bus.poll("build", after_seq=0, limit=1)
    next_page = bus.poll("build", after_seq=2, limit=1)

    assert first_page["success"] is True
    assert first_page["messages"][0]["seq"] == 2
    assert first_page["has_gap"] is True
    assert first_page["gap"] == {
        "reason": "retention",
        "requested_after_seq": 0,
        "first_retained_seq": 2,
        "last_seq": 3,
    }
    assert next_page["messages"][0]["seq"] == 3
    assert next_page["has_more"] is False


def test_pubsub_default_rebinds_to_current_app_state_store(monkeypatch, tmp_path):
    from local_ai_hub.agent_events import AgentStateStore, SwarmPubSub

    monkeypatch.setattr(SwarmPubSub, "_instance", None)
    first_store = AgentStateStore(tmp_path / "first.sqlite3")
    current_store = AgentStateStore(tmp_path / "current.sqlite3")

    bus = SwarmPubSub.get_default(state_store=first_store)
    current_bus = SwarmPubSub.get_default(state_store=current_store)

    assert current_bus is bus
    assert current_bus.state_store is current_store


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
