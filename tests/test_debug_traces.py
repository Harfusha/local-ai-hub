from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing

import pytest

from local_ai_hub import http_server
from local_ai_hub.debug_traces import DebugTraceStore


def _config(tmp_path, **overrides):
    values = {
        "enabled": True,
        "terminal_ttl_seconds": 10,
        "max_bytes": 32 * 1024 * 1024,
        "max_sessions": 100,
        "max_events_per_session": 20,
        "max_event_bytes": 2048,
        "max_session_text_bytes": 32 * 1024,
        "cleanup_batch_size": 1,
        "max_list_limit": 100,
    }
    values.update(overrides)
    return {"server": {"state_dir": str(tmp_path)}, "debug_traces": values}


def test_trace_list_defaults_to_200_and_accepts_higher_configured_limit(tmp_path):
    default_config = _config(tmp_path / "default")
    del default_config["debug_traces"]["max_list_limit"]
    assert DebugTraceStore(default_config).max_list_limit == 200
    assert DebugTraceStore(_config(tmp_path / "custom", max_list_limit=500)).max_list_limit == 500


def test_trace_defaults_allow_large_retained_payloads(tmp_path):
    config = _config(tmp_path)
    del config["debug_traces"]["max_event_bytes"]
    del config["debug_traces"]["max_session_text_bytes"]

    store = DebugTraceStore(config)

    assert store.max_event_bytes == 4 * 1024 * 1024
    assert store.max_session_text_bytes == 64 * 1024 * 1024



def test_trace_retention_days_override_terminal_ttl_and_are_reported(tmp_path):
    store = DebugTraceStore(_config(tmp_path, terminal_ttl_seconds=10, retention_days=2))
    trace_id = store.start(kind="api_request", tenant="tenant")
    store.finish(trace_id, state="done", response={"ok": True})

    with closing(sqlite3.connect(store.path)) as con:
        updated_at, expires_at = con.execute(
            "SELECT updated_at,expires_at FROM traces WHERE trace_id=?", (trace_id,)
        ).fetchone()

    assert expires_at - updated_at >= 2 * 86400 - 1
    assert store.stats()["retention_days"] == 2


def test_trace_detail_preserves_ordered_full_debug_content(tmp_path):
    store = DebugTraceStore(_config(tmp_path))
    trace_id = store.start(kind="async_job", tenant="tenant", agent="codex", action="reason")

    store.event(trace_id, "model_request", {"prompt": "full prompt", "system": "full system"})
    store.event(trace_id, "output_delta", {"text": "part"})
    store.update(trace_id, output="part")
    store.finish(trace_id, state="done", response={"text": "part"})

    detail = store.detail(trace_id, since_seq=0)
    assert detail["session"]["state"] == "done"
    assert detail["session"]["response"] == {"text": "part"}
    assert detail["session"]["output"] == "part"
    assert [event["event_type"] for event in detail["events"]] == ["model_request", "output_delta", "done"]
    assert detail["events"][0]["payload"]["prompt"] == "full prompt"


def test_trace_detail_since_seq_and_list_filters_are_bounded(tmp_path):
    store = DebugTraceStore(_config(tmp_path))
    first = store.start(kind="api_request", tenant="tenant", agent="codex", action="/api/reason", model="m1")
    store.event(first, "request_received", {"body": {"task": "inspect"}})
    second = store.start(kind="async_job", tenant="tenant", agent="worker", action="reason", model="m2")

    detail = store.detail(first, since_seq=0)
    assert [event["event_type"] for event in detail["events"]] == ["request_received"]
    listed = store.list(kind="async_job", agent="worker", limit=1, offset=0)
    assert listed["total"] == 1
    assert listed["items"][0]["trace_id"] == second


def test_trace_detail_pages_in_sequence_order_with_stable_cursor(tmp_path):
    from local_ai_hub.json_utils import dumps as json_dumps

    store = DebugTraceStore(_config(tmp_path))
    trace_id = store.start(kind="api_request", tenant="tenant", agent="codex", action="/api/reason")
    for index in range(5):
        store.event(trace_id, "output_delta", {"index": index})

    first = store.detail(trace_id, since_seq=0, limit=2)
    second = store.detail(trace_id, since_seq=first["next_seq"], limit=2)
    third = store.detail(trace_id, since_seq=second["next_seq"], limit=2)

    assert [event["seq"] for event in first["events"]] == [1, 2]
    assert [event["seq"] for event in second["events"]] == [3, 4]
    assert [event["seq"] for event in third["events"]] == [5]
    assert first["has_more"] is True
    assert second["has_more"] is True
    assert third["has_more"] is False
    assert [first["next_seq"], second["next_seq"], third["next_seq"]] == [2, 4, 5]
    assert first["events_total"] == 5
    assert first["response_bytes"] == len(json_dumps(first).encode("utf-8"))
    reset = store.detail(trace_id, since_seq=999, limit=2)
    assert reset["cursor_reset"] is True
    assert [event["seq"] for event in reset["events"]] == [1, 2]


def test_trace_detail_byte_budget_pages_at_event_boundaries(tmp_path):
    from local_ai_hub.json_utils import dumps as json_dumps

    store = DebugTraceStore(_config(tmp_path, max_event_bytes=8192))
    trace_id = store.start(kind="api_request", tenant="tenant", agent="codex", action="/api/reason")
    for index in range(8):
        store.event(trace_id, "output_delta", {"index": index, "text": "x" * 1500})

    page = store.detail(trace_id, since_seq=0, limit=100, max_bytes=5000)

    assert page["success"] is True
    assert 1 <= len(page["events"]) < 8
    assert page["page_truncated"] is True
    assert page["has_more"] is True
    assert page["next_seq"] == page["events"][-1]["seq"]
    assert page["response_bytes"] <= 5000
    assert page["response_bytes"] == len(json_dumps(page).encode("utf-8"))


def test_trace_detail_required_bytes_follow_first_trimmed_event(tmp_path):
    from local_ai_hub.json_utils import dumps as json_dumps

    store = DebugTraceStore(_config(tmp_path, max_event_bytes=8192))
    trace_id = store.start(kind="api_request", tenant="tenant", agent="codex", action="/api/reason")
    store.event(trace_id, "output_delta", {"text": "a" * 800})
    store.event(trace_id, "output_delta", {"text": "b" * 800})
    store.event(trace_id, "output_delta", {"text": "c" * 5000})

    first_event_page = store.detail(trace_id, limit=1, max_bytes=64 * 1024)
    page_budget = first_event_page["response_bytes"] + 16
    page = store.detail(trace_id, limit=100, max_bytes=page_budget)
    full = store.detail(trace_id, limit=100, max_bytes=64 * 1024)

    assert page["success"] is True
    assert page["page_truncated"] is True
    assert [event["seq"] for event in page["events"]] == [1]
    assert page["next_seq"] == 1
    assert page["oversize_seq"] == 2
    next_event = next(event for event in full["events"] if event["seq"] == page["oversize_seq"])
    candidate = dict(page)
    candidate["events"] = [*page["events"], next_event]
    candidate["next_seq"] = next_event["seq"]
    candidate["has_more"] = candidate["next_seq"] < page["last_seq"]
    candidate["page_truncated"] = False
    candidate["oversize_seq"] = None
    candidate["required_bytes"] = None
    candidate["response_bytes"] = 0
    for _ in range(5):
        required_bytes = len(json_dumps(candidate).encode("utf-8"))
        if candidate["response_bytes"] == required_bytes:
            break
        candidate["response_bytes"] = required_bytes

    assert page["required_bytes"] == required_bytes
    assert page["response_bytes"] <= page_budget


def test_trace_detail_reports_oversize_event_without_advancing_cursor(tmp_path):
    store = DebugTraceStore(_config(tmp_path, max_event_bytes=8192))
    trace_id = store.start(kind="api_request", tenant="tenant", agent="codex", action="/api/reason")
    store.event(trace_id, "output_delta", {"text": "full-payload-" + "x" * 6000})

    blocked = store.detail(trace_id, since_seq=0, limit=10, max_bytes=4096)
    recovered = store.detail(trace_id, since_seq=0, limit=10, max_bytes=16 * 1024)

    assert blocked["success"] is False
    assert blocked["error_code"] == "trace_detail_oversize"
    assert blocked["next_seq"] == 0
    assert blocked["oversize_seq"] == 1
    assert blocked["required_bytes"] > blocked["max_bytes"]
    assert blocked["response_bytes"] <= blocked["max_bytes"]
    assert recovered["success"] is True
    assert recovered["events"][0]["payload"]["text"] == "full-payload-" + "x" * 6000
    assert recovered["response_bytes"] <= recovered["max_bytes"]


def test_trace_link_and_event_payload_limits_keep_trace_bounded(tmp_path):
    store = DebugTraceStore(_config(tmp_path, max_event_bytes=100, max_session_text_bytes=120))
    trace_id = store.start(kind="api_request", tenant="tenant")
    store.link(trace_id, request_id="req-1", async_job_id="job-1", scheduler_job_id="7")
    store.event(trace_id, "request_received", {"body": "x" * 1000})
    store.update(trace_id, request={"body": "y" * 1000})

    detail = store.detail(trace_id)
    assert detail["session"]["request_id"] == "req-1"
    assert detail["session"]["async_job_id"] == "job-1"
    assert detail["session"]["scheduler_job_id"] == "7"
    assert any(event["event_type"] == "trace_truncated" for event in detail["events"])


def test_cleanup_deletes_terminal_traces_in_batches_and_protects_live_work(tmp_path):
    store = DebugTraceStore(_config(tmp_path, terminal_ttl_seconds=1, cleanup_batch_size=1))
    old_done = store.start(kind="async_job", tenant="tenant")
    store.finish(old_done, state="done", response={"ok": True})
    old_failed = store.start(kind="api_request", tenant="tenant")
    store.finish(old_failed, state="failed", error="bad")
    live = store.start(kind="async_job", tenant="tenant")
    store.update(live, state="running")

    future = time.time() + 100
    first = store.cleanup(now=future)
    assert first["deleted_sessions"] == 1
    assert store.detail(live)["session"]["state"] == "running"
    second = store.cleanup(now=future)
    assert second["deleted_sessions"] == 1
    assert store.detail(live)["session"]["state"] == "running"


def test_recover_incomplete_traces_marks_previous_processes_interrupted(tmp_path):
    store = DebugTraceStore(_config(tmp_path))
    queued = store.start(kind="api_request", tenant="tenant", action="/api/command")
    running = store.start(kind="async_job", tenant="tenant", action="reason")
    store.update(running, state="running")

    result = store.recover_incomplete(reason="hub restarted")

    assert result["recovered_sessions"] == 2
    assert store.detail(queued)["session"]["state"] == "failed"
    assert store.detail(running)["session"]["error"] == "hub restarted"
    assert store.detail(running)["terminal"] is True


def test_dashboard_and_favicon_are_monitor_paths():
    from local_ai_hub.http_server import MONITOR_PATHS

    assert "/dashboard" in MONITOR_PATHS
    assert "/favicon.ico" in MONITOR_PATHS


def test_event_count_and_session_text_caps_are_hard_limits(tmp_path):
    store = DebugTraceStore(_config(tmp_path, max_events_per_session=3, max_session_text_bytes=1024))
    trace_id = store.start(kind="async_job", tenant="tenant")
    store.event(trace_id, "one", {"text": "a"})
    store.event(trace_id, "two", {"text": "b"})
    store.event(trace_id, "three", {"text": "c"})
    store.update(trace_id, request={"body": "x" * 1000}, response={"text": "y" * 1000})

    detail = store.detail(trace_id)
    assert len(detail["events"]) <= 3
    serialized = json.dumps(detail["session"]["request"]) + json.dumps(detail["session"]["response"])
    assert len(serialized.encode("utf-8")) <= 1024


def test_http_trace_finisher_does_not_hide_a_failed_terminal_write(monkeypatch):
    from local_ai_hub import http_server

    class Store:
        def __init__(self):
            self.calls = 0

        def finish(self, trace_id, **kwargs):
            self.calls += 1
            return self.calls > 1

    class App:
        debug_traces = Store()

    handler = http_server.Handler.__new__(http_server.Handler)
    handler._debug_trace_id = "trace-id"
    handler._debug_trace_finished = False
    monkeypatch.setattr(http_server, "APP", App())

    handler._finish_debug_trace(200, {"success": True})

    assert App.debug_traces.calls == 2
    assert handler._debug_trace_finished is True


def test_model_request_promotes_model_to_trace_summary(tmp_path):
    store = DebugTraceStore(_config(tmp_path))
    trace_id = store.start(kind="async_job", tenant="tenant")

    from local_ai_hub.debug_traces import DebugTraceObserver

    DebugTraceObserver(store, trace_id).model_request({"model": "qwen2.5-coder:7b", "messages": []})

    assert store.detail(trace_id)["session"]["model"] == "qwen2.5-coder:7b"


def test_missing_debug_trace_detail_returns_not_found(monkeypatch):
    from types import SimpleNamespace

    class DebugTraces:
        TERMINAL_STATES = set()

        def detail(self, trace_id, *, since_seq, limit=100, max_bytes=8 * 1024 * 1024):
            return {"success": False, "error": "trace not found"}

    class App:
        debug_traces = DebugTraces()

    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/debug-traces/missing-trace"
    handler._begin_trace = lambda path: None
    handler._require_authorized = lambda: True
    responses = []
    handler._send = lambda status, data: responses.append((status, data))
    monkeypatch.setattr(http_server, "APP", App())
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)

    handler.do_GET()

    assert responses == [(404, {"success": False, "error": "trace not found"})]


def test_trace_detail_http_clamps_page_parameters_and_maps_oversize(tmp_path, monkeypatch):
    from types import SimpleNamespace

    store = DebugTraceStore(_config(tmp_path, max_event_bytes=8192))
    trace_id = store.start(kind="api_request", tenant="tenant", agent="codex", action="/api/reason")
    store.event(trace_id, "output_delta", {"text": "x" * 6000})
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        debug_traces=store,
        async_jobs=SimpleNamespace(path=tmp_path / "jobs.sqlite3"),
    ))
    mode_api = SimpleNamespace(
        load_operational_mode=lambda *, state_dir: SimpleNamespace(mode="active", degraded=False),
        operational_mode_gate_error=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(http_server, "_operational_mode_api", lambda: mode_api)

    def get(path):
        handler = http_server.Handler.__new__(http_server.Handler)
        handler.path = path
        handler.client_address = ("127.0.0.1", 12345)
        handler.headers = {}
        handler._begin_trace = lambda _path: None
        handler._require_authorized = lambda: True
        handler._reconcile_debug_trace = lambda session: session
        handler.responses = []
        handler._send = lambda status, data: handler.responses.append((status, data))
        handler.do_GET()
        return handler.responses

    oversized = get(
        f"/api/debug-traces/{trace_id}?since_seq=-3&limit=999999999&max_bytes=4096"
    )
    assert oversized[0][0] == 413
    assert oversized[0][1]["error_code"] == "trace_detail_oversize"
    assert oversized[0][1]["next_seq"] == 0
    assert oversized[0][1]["max_bytes"] == 4096
    assert oversized[0][1]["response_bytes"] <= 4096
    assert oversized[0][1]["response_bytes"] == len(http_server._json_bytes(oversized[0][1]))

    complete = get(
        f"/api/debug-traces/{trace_id}?since_seq=-3&limit=999999999&max_bytes=999999999"
    )
    assert complete[0][0] == 200
    assert complete[0][1]["limit"] == 1000
    assert complete[0][1]["max_bytes"] == 8 * 1024 * 1024
    assert complete[0][1]["next_seq"] == 1
    assert complete[0][1]["events"][0]["payload"]["text"] == "x" * 6000
    assert complete[0][1]["response_bytes"] <= 8 * 1024 * 1024
    assert complete[0][1]["response_bytes"] == len(http_server._json_bytes(complete[0][1]))

    default_budget = get(f"/api/debug-traces/{trace_id}")
    assert default_budget[0][0] == 200
    assert default_budget[0][1]["max_bytes"] == 8 * 1024 * 1024
    assert default_budget[0][1]["response_bytes"] <= 8 * 1024 * 1024


def test_trace_detail_http_rebuilds_page_after_reconciliation(tmp_path, monkeypatch):
    from types import SimpleNamespace

    class DebugTraces:
        TERMINAL_STATES = {"done", "failed", "cancelled", "expired"}

        def __init__(self):
            self.calls = []

        def detail(self, trace_id, **kwargs):
            self.calls.append((trace_id, kwargs))
            session = {"state": "running", "error": ""} if len(self.calls) == 1 else {
                "state": "done", "error": "", "finished_at": 1.0,
            }
            result = {
                "success": True,
                "session": session,
                "events": [],
                "terminal": session["state"] in self.TERMINAL_STATES,
                "response_bytes": 0,
            }
            for _ in range(5):
                size = len(http_server._json_bytes(result))
                if result["response_bytes"] == size:
                    break
                result["response_bytes"] = size
            return result

    traces = DebugTraces()
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        debug_traces=traces,
        async_jobs=SimpleNamespace(path=tmp_path / "jobs.sqlite3"),
    ))
    mode_api = SimpleNamespace(
        load_operational_mode=lambda *, state_dir: SimpleNamespace(mode="active", degraded=False),
        operational_mode_gate_error=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(http_server, "_operational_mode_api", lambda: mode_api)
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/debug-traces/trace-1?since_seq=0&limit=2&max_bytes=4096"
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {}
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    handler._reconcile_debug_trace = lambda session: session.update(state="done", finished_at=1.0) or session
    handler.responses = []
    handler._send = lambda status, data: handler.responses.append((status, data))

    handler.do_GET()

    assert len(traces.calls) == 2
    assert traces.calls[0] == traces.calls[1]
    assert handler.responses[0][0] == 200
    assert handler.responses[0][1]["session"]["state"] == "done"
    assert handler.responses[0][1]["terminal"] is True
    assert handler.responses[0][1]["response_bytes"] == len(http_server._json_bytes(handler.responses[0][1]))
@pytest.mark.parametrize("since_seq", [2**63 - 1, 2**63, 2**100])
def test_trace_detail_clamps_forward_cursor_and_reports_retained_reset(tmp_path, since_seq):
    store = DebugTraceStore(_config(tmp_path))
    trace_id = store.start(kind="async_job", tenant="tenant", action="reason")
    store.event(trace_id, "progress", {"index": 1})

    detail = store.detail(trace_id, since_seq=since_seq)

    assert detail["success"] is True
    assert detail["cursor_reset"] is True
    assert detail["first_retained_seq"] == 1
    assert detail["next_seq"] == 1
    assert [event["seq"] for event in detail["events"]] == [1]
