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


def test_detailed_traces_default_to_off_without_explicit_opt_in(tmp_path):
    store = DebugTraceStore({"server": {"state_dir": str(tmp_path)}})
    assert store.enabled is False
    assert store.start(kind="api_request", tenant="test", action="/api/test") == ""


def test_trace_defaults_allow_large_retained_payloads(tmp_path):
    config = _config(tmp_path)
    del config["debug_traces"]["max_event_bytes"]
    del config["debug_traces"]["max_session_text_bytes"]

    store = DebugTraceStore(config)

    assert store.max_event_bytes == 8 * 1024 * 1024
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
    past_end = store.detail(trace_id, since_seq=999, limit=2)
    assert past_end["cursor_reset"] is False
    assert past_end["events"] == []


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
def test_trace_list_skips_empty_project_before_root_fallback(tmp_path):
    store = DebugTraceStore(_config(tmp_path))
    trace_id = store.start(kind="api_request", tenant="tenant", action="/api/reason")
    store.update(trace_id, request={"project": "", "root": r"C:\projects\alpha"})

    listed = store.list()

    assert listed["items"][0]["project"] == "alpha"


@pytest.mark.parametrize("offset", [2**63 - 1, 2**63, 2**100])
def test_trace_list_accepts_offsets_beyond_sqlite_integer_range(tmp_path, offset):
    store = DebugTraceStore(_config(tmp_path))
    store.start(kind="async_job", tenant="tenant", action="reason")

    listed = store.list(offset=offset)

    assert listed["success"] is True
    assert listed["total"] == 1
    assert listed["offset"] == offset
    assert listed["items"] == []


def test_debug_trace_list_route_handles_sqlite_oversized_offset(tmp_path, monkeypatch):
    offset = 2**100
    store = DebugTraceStore(_config(tmp_path))
    store.start(kind="async_job", tenant="tenant", action="reason")
    app = type("App", (), {"debug_traces": store})()
    monkeypatch.setattr(http_server, "APP", app)

    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = f"/api/debug-traces?offset={offset}"
    handler.command = "GET"
    handler._begin_trace = lambda path: None
    handler._require_authorized = lambda: True
    handler._authorization_succeeded = True
    handler._authorize_admin_action = lambda action: action == "debug_traces.list"
    handler._reconcile_debug_trace = lambda item: None
    responses = []
    handler._send = lambda status, data: responses.append((status, data))

    handler.do_GET()

    assert responses == [(
        200,
        {"success": True, "items": [], "total": 1, "limit": 50, "offset": offset},
    )]


@pytest.mark.parametrize("since_seq", [2**63 - 1, 2**63, 2**100])
def test_trace_detail_clamps_forward_cursor_to_sqlite_integer_range(tmp_path, since_seq):
    store = DebugTraceStore(_config(tmp_path))
    trace_id = store.start(kind="async_job", tenant="tenant", action="reason")
    store.event(trace_id, "progress", {"index": 1})

    detail = store.detail(trace_id, since_seq=since_seq)

    assert detail["success"] is True
    assert detail["events"] == []


def test_trace_detail_supports_bounded_backward_event_pages(tmp_path):
    store = DebugTraceStore(_config(tmp_path))
    trace_id = store.start(kind="async_job", tenant="tenant", action="reason")
    for index in range(5):
        store.event(trace_id, "progress", {"index": index})

    newest_older_page = store.detail(trace_id, before_seq=6, limit=2)
    oldest_page = store.detail(trace_id, before_seq=newest_older_page["events_before_seq"], limit=2)
    first_page = store.detail(trace_id, before_seq=oldest_page["events_before_seq"], limit=2)

    assert [event["seq"] for event in newest_older_page["events"]] == [4, 5]
    assert newest_older_page["events_has_more"] is True
    assert newest_older_page["events_before_seq"] == 4
    assert [event["seq"] for event in oldest_page["events"]] == [2, 3]
    assert oldest_page["events_has_more"] is True
    assert [event["seq"] for event in first_page["events"]] == [1]
    assert first_page["events_has_more"] is False


def test_backward_page_size_trimming_does_not_claim_older_events(tmp_path):
    store = DebugTraceStore(
        _config(
            tmp_path,
            max_detail_response_bytes=4096,
            max_event_bytes=16 * 1024,
            max_session_text_bytes=16 * 1024,
        )
    )
    trace_id = store.start(kind="async_job", tenant="tenant")
    store.event(trace_id, "progress", {"payload": "x" * 5000})
    encode = store._encode
    store._encode = lambda value: encode(value) + (" " * 6000 if isinstance(value, dict) and value.get("events") else "")

    detail = store.detail(trace_id, before_seq=2, limit=1, full_payload=True)

    assert detail["events"] == []
    assert detail["events_has_more"] is False


def test_forward_page_size_trimming_preserves_cursor_for_omitted_events(tmp_path):
    store = DebugTraceStore(_config(tmp_path, max_detail_response_bytes=4096))
    trace_id = store.start(kind="async_job", tenant="tenant")
    store.event(trace_id, "progress", {"index": 1})
    store.event(trace_id, "progress", {"index": 2})
    encode = store._encode
    store._encode = lambda value: encode(value) + (" " * 6000 if isinstance(value, dict) and len(value.get("events", [])) > 1 else "")

    detail = store.detail(trace_id, since_seq=0, limit=2)

    assert [event["seq"] for event in detail["events"]] == [1]
    assert detail["events_has_more"] is True
    assert detail["next_seq"] == 1


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
    from local_ai_hub.dashboard import DASHBOARD_HTML

    assert "/dashboard" in MONITOR_PATHS
    assert "/favicon.ico" in MONITOR_PATHS
    assert "Podrobný obsah je vypnutý" in DASHBOARD_HTML
    assert "Podrobná telemetrie ukládá úplný endpoint input/output lokálně" in DASHBOARD_HTML
    assert "data-trace-reveal" not in DASHBOARD_HTML
    assert "Obsah zkrácen limitem trace úložiště" in DASHBOARD_HTML


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

        def detail(
            self,
            trace_id,
            *,
            since_seq,
            limit=100,
            max_bytes=8 * 1024 * 1024,
            before_seq=0,
            full_payload=False,
            content_field="",
            content_offset=0,
        ):
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



def test_full_payload_detail_marks_content_beyond_bounded_preview(tmp_path):
    store = DebugTraceStore(_config(tmp_path, max_session_text_bytes=2 * 1024 * 1024))
    trace_id = store.start(kind="async_job", tenant="tenant", action="reason")
    output = "x" * 600_000
    store.update(trace_id, output=output)

    detail = store.detail(trace_id, full_payload=True)

    assert detail["full_payload_requested"] is True
    assert detail["payload_truncated"] is True
    assert detail["session"]["output"]["truncated"] is True
    assert len(detail["session"]["output"]["preview"]) < len(output)


def test_full_payload_content_pages_reconstruct_retained_session_and_event_data(tmp_path):
    store = DebugTraceStore(_config(
        tmp_path,
        max_session_text_bytes=2 * 1024 * 1024,
        max_event_bytes=4096,
        max_detail_response_bytes=4096,
    ))
    trace_id = store.start(kind="async_job", tenant="tenant", action="reason")
    output = "start-秘密-😀-" + "x" * 5000 + "-end"
    response = {"message": "結果-" + "y" * 1500}
    event_payload = {"prompt": "入力-" + "z" * 1000}
    store.event(trace_id, "model_request", event_payload)
    store.update(trace_id, output=output)
    store.finish(trace_id, state="done", response=response)

    def collect(field):
        parts = []
        offset = 0
        while True:
            detail = store.detail(
                trace_id,
                full_payload=True,
                content_field=field,
                content_offset=offset,
            )
            assert detail["success"] is True
            page = detail["content_page"]
            assert len(json.dumps(detail, ensure_ascii=False).encode("utf-8")) <= store.max_detail_response_bytes
            assert page["offset"] == offset
            parts.append(page["text"])
            if not page["has_more"]:
                break
            assert page["next_offset"] > offset
            offset = page["next_offset"]
        return "".join(parts)

    assert collect("output") == output
    assert json.loads(collect("response")) == response
    assert json.loads(collect("event:1")) == event_payload
    last_page = store.detail(trace_id, full_payload=True, content_field="output", content_offset=2**63 - 1)
    assert last_page["success"] is True
    assert last_page["content_page"]["offset"] == len(output)


def test_large_unicode_content_pages_use_indexed_chunks_at_late_offsets(tmp_path):
    store = DebugTraceStore(_config(
        tmp_path,
        max_session_text_bytes=8 * 1024 * 1024,
        max_event_bytes=4 * 1024 * 1024,
        max_detail_response_bytes=4096,
    ))
    trace_id = store.start(kind="async_job", tenant="tenant", action="reason")
    output = "秘密😀" * 100_000
    response = {"answer": "結果🛰️" * 30_000}
    event_payload = {"prompt": "入力🪷" * 25_000}
    store.update(trace_id, output=output, response=response)
    store.event(trace_id, "model_request", event_payload)

    offset = len(output) - 700
    output_page = store.detail(
        trace_id, full_payload=True, content_field="output", content_offset=offset
    )
    response_text = store._encode(response)
    response_offset = len(response_text) - 350
    response_page = store.detail(
        trace_id, full_payload=True, content_field="response", content_offset=response_offset
    )
    event_text = store._encode(event_payload)
    event_offset = len(event_text) - 450
    event_page = store.detail(
        trace_id, full_payload=True, content_field="event:1", content_offset=event_offset
    )

    assert output_page["success"] is True
    assert output_page["content_page"]["text"] == output[offset:offset + 256]
    assert output_page["content_page"]["total_chars"] == len(output)
    assert response_page["success"] is True
    assert response_page["content_page"]["text"] == response_text[response_offset:response_offset + 256]
    assert response_page["content_page"]["total_chars"] == len(response_text)
    assert event_page["success"] is True
    assert event_page["content_page"]["text"] == event_text[event_offset:event_offset + 256]
    assert event_page["content_page"]["total_chars"] == len(event_text)

    with closing(store._connect()) as con:
        max_chunk_chars = con.execute(
            "SELECT MAX(length(chunk_text)) FROM trace_content_chunks WHERE trace_id=?",
            (trace_id,),
        ).fetchone()[0]
        preview_chars = con.execute(
            "SELECT length(output_text) FROM traces WHERE trace_id=?", (trace_id,)
        ).fetchone()[0]
        event_preview_chars = con.execute(
            "SELECT length(payload_json) FROM trace_events WHERE trace_id=? AND seq=1",
            (trace_id,),
        ).fetchone()[0]
        plan = con.execute(
            "EXPLAIN QUERY PLAN SELECT chunk_index,chunk_text FROM trace_content_chunks "
            "WHERE trace_id=? AND content_field=? AND event_seq=? AND chunk_index>=? "
            "AND chunk_index<? ORDER BY chunk_index LIMIT ?",
            (trace_id, "output", 0, 10, 11, 2),
        ).fetchall()

    assert max_chunk_chars <= store.CONTENT_CHUNK_CHARS
    assert preview_chars <= store.CONTENT_PREVIEW_CHARS
    assert event_preview_chars <= store.CONTENT_PREVIEW_CHARS
    assert any("SEARCH" in str(row[3]) and "trace_content_chunks" in str(row[3]) for row in plan)


def test_detail_flags_event_payload_truncated_before_response_serialization(tmp_path):
    store = DebugTraceStore(_config(tmp_path, max_event_bytes=256, max_session_text_bytes=1024))
    trace_id = store.start(kind="async_job", tenant="tenant", action="reason")
    store.event(trace_id, "model_request", {"prompt": "p" * 2000})

    detail = store.detail(trace_id, full_payload=True)

    assert detail["payload_truncated"] is True
    assert any(event["payload"].get("truncated") is True for event in detail["events"])


def test_detail_flags_session_fields_truncated_before_response_serialization(tmp_path):
    store = DebugTraceStore(_config(tmp_path, max_session_text_bytes=1024))
    trace_id = store.start(kind="async_job", tenant="tenant", action="reason")
    store.update(trace_id, output="o" * 6000, request={"body": "r" * 6000})

    detail = store.detail(trace_id, full_payload=True)

    assert detail["payload_truncated"] is True
    assert detail["session"]["request"]["truncated"] is True
    assert "[trace output truncated]" in detail["session"]["output"]


def test_http_trace_request_capture_keeps_complete_content_and_credentials():
    from local_ai_hub.http_server import Handler

    captured = Handler._safe_debug_trace_request({
        "prompt": "keep this trace content",
        "headers": {"authorization": "Bearer secret", "nested": {"api_key": "secret-key"}},
    })

    assert captured["prompt"] == "keep this trace content"
    assert captured["headers"]["authorization"] == "Bearer secret"
    assert captured["headers"]["nested"]["api_key"] == "secret-key"
    assert "capture_status" not in captured
    assert "Bearer secret" in json.dumps(captured)
    assert "secret-key" in json.dumps(captured)


def test_http_trace_request_metadata_keeps_complete_project_path():
    from local_ai_hub.http_server import Handler

    captured = Handler._safe_debug_trace_request(
        {"project": "", "root": r"C:\work\project-alpha", "prompt": "private prompt"}
    )

    assert captured["project"] == ""
    assert captured["root"] == r"C:\work\project-alpha"
    assert captured["prompt"] == "private prompt"
    assert r"C:\work\project-alpha" in captured["root"]


def test_debug_trace_route_forwards_bounded_content_page_cursor(monkeypatch):
    class DebugTraces:
        TERMINAL_STATES = set()
        captured = None

        def detail(self, trace_id, **kwargs):
            self.captured = (trace_id, kwargs)
            return {"success": True, "content_page": {"field": "output", "offset": 128}}

    class App:
        debug_traces = DebugTraces()

    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/debug-traces/trace-1?full=1&content_field=output&content_offset=128"
    handler.command = "GET"
    handler._begin_trace = lambda path: None
    handler._require_authorized = lambda: True
    handler._authorization_succeeded = True
    responses = []
    handler._send = lambda status, data: responses.append((status, data))
    monkeypatch.setattr(http_server, "APP", App())

    handler.do_GET()

    assert App.debug_traces.captured == (
        "trace-1",
        {
            "since_seq": 0,
            "limit": 100,
            "max_bytes": http_server.DEBUG_TRACE_HTTP_MAX_BYTES,
            "before_seq": 0,
            "full_payload": True,
            "content_field": "output",
            "content_offset": 128,
        },
    )
    assert responses == [(200, {"success": True, "content_page": {"field": "output", "offset": 128}})]


@pytest.mark.parametrize("since_seq", [2**63 - 1, 2**63, 2**100])
def test_trace_detail_clamps_forward_cursor_without_replaying_events(tmp_path, since_seq):
    store = DebugTraceStore(_config(tmp_path))
    trace_id = store.start(kind="async_job", tenant="tenant", action="reason")
    store.event(trace_id, "progress", {"index": 1})

    detail = store.detail(trace_id, since_seq=since_seq)

    assert detail["success"] is True
    assert detail["cursor_reset"] is False
    assert detail["first_retained_seq"] == 1
    assert detail["next_seq"] == min(since_seq, 2**63 - 1)
    assert detail["events"] == []
