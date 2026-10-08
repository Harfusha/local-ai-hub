from __future__ import annotations

import io
import sqlite3
from contextlib import closing
from types import SimpleNamespace

from local_ai_hub import http_server
from local_ai_hub.agent_events import AgentEvent, AgentStateStore


def _handler(store, monkeypatch, writer=None):
    app = SimpleNamespace(
        agent_state=store, config={"server": {"max_stream_duration_seconds": 1}},
        logger=SimpleNamespace(warning=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(http_server, "APP", app)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.headers = {}
    handler.wfile = writer if writer is not None else io.BytesIO()
    handler.send_response = lambda *args: None
    handler.send_header = lambda *args: None
    handler.end_headers = lambda: None
    handler._common_headers = lambda: None
    handler._finish_stream_request = lambda success, **kwargs: setattr(handler, "stream_result", success)
    return handler


def _gapped_store(tmp_path):
    store = AgentStateStore(tmp_path / "events.sqlite3")
    for seq in range(1, 6):
        store.append(AgentEvent.create("task-1", "task.updated", {"step": seq}, f"k{seq}"))
    with closing(sqlite3.connect(store.db_path)) as connection:
        connection.execute("DELETE FROM agent_events WHERE stream_id = ? AND seq IN (2, 4)", ("task-1",))
        connection.commit()
    return store


def test_replay_cursors_never_skip_earlier_events_between_retention_gaps(tmp_path, monkeypatch):
    handler = _handler(_gapped_store(tmp_path), monkeypatch)

    handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=0.001)

    output = handler.wfile.getvalue().decode("utf-8")
    cursors = [int(line[4:]) for line in output.splitlines() if line.startswith("id: ")]
    assert cursors == [1, 2, 3, 4, 5]
    assert output.count("event: task.updated") == 3
    assert output.count("event: stream.gap") == 2
    assert handler.stream_result is True


def test_disconnect_then_header_resume_does_not_lose_replay_events(tmp_path, monkeypatch):
    class DisconnectBeforeGap(io.BytesIO):
        def write(self, data):
            if data.startswith(b"id: 2\n"):
                raise BrokenPipeError("client disconnected")
            return super().write(data)

    store = _gapped_store(tmp_path)
    first = _handler(store, monkeypatch, DisconnectBeforeGap())
    first._stream_agent_events(stream_id="task-1", after_seq=0, timeout=0.001)
    assert [line for line in first.wfile.getvalue().splitlines() if line.startswith(b"id: ")] == [b"id: 1"]
    assert first.stream_result is False
    resumed = _handler(store, monkeypatch)
    resumed.headers = {"Last-Event-ID": "1"}
    resumed._stream_agent_events(stream_id="task-1", after_seq=0, timeout=0.001)
    output = resumed.wfile.getvalue().decode()
    assert [int(line[4:]) for line in output.splitlines() if line.startswith("id: ")] == [2, 3, 4, 5]
    assert output.count("event: task.updated") == 2
    assert resumed.stream_result is True


def test_user_event_named_stream_gap_is_not_treated_as_retention_metadata(tmp_path, monkeypatch):
    store = AgentStateStore(tmp_path / "events.sqlite3")
    store.append(AgentEvent.create("task-1", "stream.gap", {"step": 1}, "k1"))
    handler = _handler(store, monkeypatch)
    handler._stream_agent_events(stream_id="task-1", after_seq=0, timeout=0.001)
    output = handler.wfile.getvalue().decode()
    assert "id: 1\nevent: stream.gap" in output
    assert '"payload":{"step":1}' in output
    assert handler.stream_result is True


def test_filtered_page_advances_cursor_only_after_processing_the_page(tmp_path, monkeypatch):
    store = AgentStateStore(tmp_path / "events.sqlite3")
    for seq in range(1, 6):
        store.append(AgentEvent.create("task-1", "task.progress", {"step": seq}, f"k{seq}"))
    handler = _handler(store, monkeypatch)
    handler._stream_agent_events(stream_id="task-1", kind="task.done", after_seq=0, timeout=0.001)
    output = handler.wfile.getvalue().decode()
    assert [line for line in output.splitlines() if line.startswith("id: ")] == ["id: 5"]
    assert "event: task.progress" not in output
    assert "id: 5\nevent: replay_page" in output
    assert handler.stream_result is True
