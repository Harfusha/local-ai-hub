from __future__ import annotations

import json
import time

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
