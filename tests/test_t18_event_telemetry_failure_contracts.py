from __future__ import annotations

import io
import json
import logging
import queue
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from local_ai_hub import http_server


def _http_get_handler(monkeypatch, *, app, path: str):
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = path
    handler.command = "GET"
    handler.headers = {"Authorization": "Bearer t18-test-api-token"}
    handler.client_address = ("127.0.0.1", 12345)
    handler.server = SimpleNamespace()
    handler._begin_trace = lambda _path: None
    handler.responses = []
    handler._send = lambda status, payload: handler.responses.append((status, payload))
    return handler


def _scoped_app(tmp_path, **components):
    root = tmp_path / "repo"
    root.mkdir()
    session_id = "session-t18-event-test"
    task = SimpleNamespace(
        task_id="task-1",
        context=SimpleNamespace(repository_id=str(root.resolve()), session_id=session_id),
        checkpoint=SimpleNamespace(
            state_data={
                "_agent_task_scope": {"version": 2, "repo_root": str(root.resolve())}
            }
        ),
    )
    config = {
        "security": {
            "api_token": "t18-test-api-token",
            "allowed_roots": [str(root.resolve())],
        }
    }
    app = SimpleNamespace(
        config=config,
        logger=logging.getLogger("test.t18.http"),
        agent_tasks=SimpleNamespace(get=lambda task_id: task if task_id == "task-1" else None),
        **components,
    )
    return app, root


def test_event_page_provider_failure_returns_retryable_page_error(monkeypatch, tmp_path):
    class BrokenEventStore:
        enabled = True
        calls = []

        def event_page(self, **_kwargs):
            self.calls.append(_kwargs)
            raise TimeoutError("database wait expired")

        def events(self, **_kwargs):
            raise AssertionError("route must not fall back to unpaged event reads")

    app, root = _scoped_app(tmp_path, agent_state=BrokenEventStore())
    path = "/api/agent-state/events?" + urlencode(
        {"stream_id": "task:task-1", "root": str(root.resolve()), "after_seq": 7, "limit": 20}
    )
    handler = _http_get_handler(monkeypatch, app=app, path=path)

    handler.do_GET()

    status, payload = handler.responses[0]
    assert status == 503, handler.responses
    assert payload["success"] is False
    assert handler._authorization_root == str(root.resolve())
    assert handler._authorization_root == str(root.resolve())
    assert payload["next_seq"] == 7
    assert payload["error"]["code"] == "event_page_unavailable"
    assert payload["retryable"] is True


@pytest.mark.parametrize("failure_page", [1, 2])
def test_event_stream_provider_failure_emits_retryable_replay_error(monkeypatch, failure_page):
    class BrokenEventStore:
        enabled = True
        unsubscribed = False
        pages = 0

        def subscribe(self, maxsize=200):
            return queue.Queue(maxsize=maxsize)

        def event_page(self, **_kwargs):
            self.pages += 1
            if self.pages < failure_page:
                return {
                    "success": True,
                    "events": [{"seq": 8, "stream_id": "task:task-1", "kind": "task.created", "payload": {}}],
                    "next_seq": 8,
                    "last_seq": 9,
                    "has_more": True,
                    "gap_ranges": [],
                }
            raise TimeoutError("database wait expired")

        def unsubscribe(self, _subscriber):
            self.unsubscribed = True

    store = BrokenEventStore()
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            config={"server": {"max_stream_duration_seconds": 1}},
            logger=logging.getLogger("test.t18.stream"),
            agent_state=store,
        ),
    )
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.headers = {}
    handler.wfile = io.BytesIO()
    handler.send_response = lambda _status: None
    handler.send_header = lambda _name, _value: None
    handler.end_headers = lambda: None
    handler._common_headers = lambda: None
    finishes = []
    handler._finish_stream_request = lambda success, **kwargs: finishes.append((success, kwargs))

    handler._stream_agent_events(stream_id="task:task-1", after_seq=7, timeout=0.01)

    output = handler.wfile.getvalue().decode("utf-8")
    if failure_page == 1:
        payload = json.loads(output)
        assert payload["error"]["code"] == "event_page_unavailable"
    else:
        assert "event: replay_error" in output
        error_frame = next(frame for frame in output.split("\n\n") if "event: replay_error" in frame)
        data = next(line[6:] for line in error_frame.splitlines() if line.startswith("data: "))
        payload = json.loads(data)
        assert payload["error"]["code"] == "event_replay_unavailable"
    assert payload["retryable"] is True
    assert payload["terminal"] is False
    assert payload["next_seq"] == (7 if failure_page == 1 else 8)
    assert store.pages == failure_page
    assert store.unsubscribed is True
    assert finishes and finishes[0][0] is False


def test_telemetry_timeline_get_provider_failure_is_retryable(monkeypatch, tmp_path):
    class BrokenTelemetry:
        def record_system(self, *_args, **_kwargs):
            return None

        def get_timeline_page(self, *_args, **_kwargs):
            raise TimeoutError("telemetry query deadline")

    app, _root = _scoped_app(tmp_path, telemetry=BrokenTelemetry())
    handler = _http_get_handler(monkeypatch, app=app, path="/api/telemetry/timeline?limit=20&before_id=10")

    handler.do_GET()

    status, payload = handler.responses[0]
    assert status == 503
    assert payload["success"] is False
    assert payload["error"]["code"] == "telemetry_page_unavailable", payload
    assert payload["retryable"] is True
    assert payload["terminal"] is False


def test_telemetry_timeline_post_provider_failure_is_retryable(monkeypatch):
    class BrokenTelemetry:
        def get_timeline_page(self, *_args, **_kwargs):
            raise TimeoutError("telemetry query deadline")

    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            config={},
            logger=logging.getLogger("test.t18.post"),
            telemetry=BrokenTelemetry(),
        ),
    )
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.responses = []
    handler._send = lambda status, payload: handler.responses.append((status, payload))

    handler._handle_post_telemetry_timeline({"limit": 20, "before_id": 10})

    status, payload = handler.responses[0]
    assert status == 503
    assert payload["success"] is False
    assert payload["error"]["code"] == "telemetry_page_unavailable"
    assert payload["retryable"] is True
    assert payload["terminal"] is False
