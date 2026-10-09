from __future__ import annotations

import json
import multiprocessing

import pytest

from local_ai_hub import operational_mode
from local_ai_hub.operational_mode import load_operational_mode, set_operational_mode


def _set_mode_in_child(state_dir, started, completed):
    started.set()
    set_operational_mode(state_dir, "maintenance")
    completed.set()


def _set_modes_repeatedly(state_dir, count, mode):
    for _ in range(count):
        set_operational_mode(state_dir, mode)


def test_missing_mode_file_defaults_to_active(tmp_path):
    snapshot = load_operational_mode(tmp_path)

    assert snapshot.mode == "active"
    assert snapshot.revision == 0
    assert snapshot.degraded is False
    assert snapshot.error == ""


def test_mode_updates_are_persisted_and_increment_revision(tmp_path):
    first = set_operational_mode(tmp_path, "gaming")
    second = set_operational_mode(tmp_path, "maintenance")

    assert first.mode == "gaming"
    assert first.revision == 1
    assert second.mode == "maintenance"
    assert second.revision == 2
    assert load_operational_mode(tmp_path) == second
    assert json.loads((tmp_path / "operational_mode.json").read_text(encoding="utf-8"))["mode"] == "maintenance"


def test_mode_update_waits_for_writer_in_another_process(tmp_path):
    context = multiprocessing.get_context("spawn")
    started = context.Event()
    completed = context.Event()
    child = context.Process(
        target=_set_mode_in_child,
        args=(str(tmp_path), started, completed),
    )

    with operational_mode._state_writer_lock(tmp_path):
        child.start()
        assert started.wait(10)
        assert not completed.wait(0.25)

    child.join(10)
    assert child.exitcode == 0
    assert completed.is_set()
    assert load_operational_mode(tmp_path).revision == 1


def test_mode_updates_from_multiple_processes_do_not_lose_revisions(tmp_path):
    context = multiprocessing.get_context("spawn")
    workers = [
        context.Process(target=_set_modes_repeatedly, args=(str(tmp_path), 4, mode))
        for mode in ("gaming", "maintenance", "active")
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(10)
        assert worker.exitcode == 0

    assert load_operational_mode(tmp_path).revision == 12


def test_mode_replace_retries_windows_sharing_violation(monkeypatch, tmp_path):
    real_replace = operational_mode.os.replace
    calls = 0

    def replace_with_sharing_violation(source, target):
        nonlocal calls
        calls += 1
        if calls == 1:
            error = OSError("sharing violation")
            error.winerror = 32
            raise error
        real_replace(source, target)

    monkeypatch.setattr(operational_mode.os, "replace", replace_with_sharing_violation)
    monkeypatch.setattr(operational_mode.time, "sleep", lambda _delay: None)

    result = set_operational_mode(tmp_path, "gaming")

    assert result.mode == "gaming"
    assert calls == 2


def test_mode_replace_sharing_violation_retry_is_bounded(monkeypatch, tmp_path):
    calls = 0
    clock = iter((0.0, 0.0, 0.0, 2.0))

    def always_sharing_locked(_source, _target):
        nonlocal calls
        calls += 1
        error = OSError("sharing violation")
        error.winerror = 32
        raise error

    class _Clock:
        def monotonic(self):
            return next(clock)

        def sleep(self, _delay):
            pass

    monkeypatch.setattr(operational_mode.os, "replace", always_sharing_locked)
    monkeypatch.setattr(operational_mode, "time", _Clock())

    with pytest.raises(OSError, match="sharing violation"):
        set_operational_mode(tmp_path, "maintenance")

    assert calls == 2


def test_mode_update_retries_transient_replace_permission_error(tmp_path, monkeypatch):
    set_operational_mode(tmp_path, "gaming")
    original_replace = operational_mode.os.replace
    calls = 0

    def replace_with_one_transient_failure(source, destination):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PermissionError("transient sharing violation")
        return original_replace(source, destination)

    monkeypatch.setattr(operational_mode.os, "replace", replace_with_one_transient_failure)

    result = set_operational_mode(tmp_path, "maintenance")

    assert calls == 2
    assert result.mode == "maintenance"
    assert load_operational_mode(tmp_path) == result


def test_corrupt_mode_fails_closed_to_maintenance(tmp_path):
    (tmp_path / "operational_mode.json").write_text("{", encoding="utf-8")

    snapshot = load_operational_mode(tmp_path)

    assert snapshot.mode == "maintenance"
    assert snapshot.degraded is True
    assert snapshot.error


def test_mode_invalid_utf8_fails_closed_and_can_recover(tmp_path):
    state_path = tmp_path / "operational_mode.json"
    state_path.write_bytes(b"{\"mode\":\"active\",\xff}")

    snapshot = load_operational_mode(tmp_path)

    assert snapshot.mode == "maintenance"
    assert snapshot.revision == 0
    assert snapshot.degraded is True
    assert snapshot.error == "operational mode state is invalid"

    recovered = set_operational_mode(tmp_path, "active")
    assert recovered.mode == "active"
    assert recovered.revision == 1
    assert load_operational_mode(tmp_path) == recovered


def test_invalid_mode_is_rejected_without_replacing_persisted_state(tmp_path):
    original = set_operational_mode(tmp_path, "gaming")

    with pytest.raises(ValueError):
        set_operational_mode(tmp_path, "paused")

    assert load_operational_mode(tmp_path) == original


def test_mcp_agent_inference_is_rejected_before_dispatch_but_status_remains_available(monkeypatch, tmp_path):
    from local_ai_hub import mcp_server

    set_operational_mode(tmp_path, "gaming")
    monkeypatch.setattr(mcp_server, "configured_state_dir", lambda *_args, **_kwargs: tmp_path)
    adoption_calls = []
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *args, **kwargs: adoption_calls.append(args))

    rejected = mcp_server.local_ai_task(action="delegate", task="review the current change")

    assert rejected["mode"] == "gaming"
    assert rejected["error"] == "hub paused: gaming mode active"
    assert rejected["terminal"] is False
    assert rejected["retryable"] is True
    assert 0 < rejected["retry_after_seconds"] <= 10
    assert adoption_calls == []

    status_calls = []
    monkeypatch.setattr(mcp_server.FEATURES, "status", True)
    monkeypatch.setattr(
        mcp_server.CLIENT,
        "get",
        lambda path: status_calls.append(path) or {"hub_online": True, "runtime_stats": {}},
    )
    mcp_server.local_ai_status(action="health")
    assert status_calls

    set_operational_mode(tmp_path, "maintenance")
    maintenance_status = mcp_server.local_ai_status(action="health")
    assert maintenance_status["success"] is True
    assert "mode" not in maintenance_status
    assert len(status_calls) == 2


def test_http_mode_routes_read_and_update_persisted_mode(monkeypatch, tmp_path):
    from local_ai_hub import http_server

    unload_calls = []
    release_events = []
    release_tokens = set()
    mode_changes = []
    guard_state = []

    def unload_configured_models(_self, **kwargs):
        assert guard_state[-1] == "exited"
        assert release_tokens == {"gaming"}
        unload_calls.append(kwargs)
        release_events.append("unloaded")
        return {
            "success": True, "backend_available": True, "unloaded": ["model-a"], "failed": {},
        }

    runtime = type("Runtime", (), {
        "unload_configured_models": unload_configured_models,
    })()

    class ModeGuard:
        def __enter__(self):
            guard_state.append("entered")

        def __exit__(self, *_exc):
            guard_state.append("exited")

    def mode_changed(_self, snapshot):
        assert guard_state == ["entered"]
        mode_changes.append((snapshot, load_operational_mode(tmp_path)))

    async_jobs = type("AsyncJobs", (), {
        "operational_mode_change_guard": lambda self: ModeGuard(),
        "on_operational_mode_changed": mode_changed,
        "resource_release_active": lambda self: bool(release_tokens),
        "begin_resource_release": lambda self: (release_tokens.add("gaming"), release_events.append("reserved"), "gaming")[-1],
        "end_resource_release": lambda self, token: (release_tokens.discard(token), release_events.append("released")),
        "wait_for_inference_actions": lambda self, _actions, _timeout: True,
        "inference_actions_active": lambda self, **_kwargs: False,
    })()
    monkeypatch.setattr(http_server, "APP", type("App", (), {
        "config": {"server": {"state_dir": str(tmp_path)}}, "runtime": runtime, "async_jobs": async_jobs,
    })())
    responses = []
    handler = type("MockHandler", (), {
        "path": "/api/mode",
        "headers": {},
        "client_address": ("127.0.0.1", 0),
        "_begin_trace": lambda self, _path: None,
        "_validate_host_and_origin": lambda self: True,
        "_require_authorized": lambda self: True,
        "_send": lambda self, status, payload: responses.append((status, payload)),
    })()

    http_server.Handler.do_GET(handler)
    assert responses[-1][0] == 200
    assert responses[-1][1]["mode"] == "active"

    handler.path = "/api/admin/mode"
    handler._read_json = lambda: {"mode": "gaming"}
    http_server.Handler.do_POST(handler)
    assert responses[-1][0] == 200
    assert responses[-1][1]["mode"] == "gaming"
    assert mode_changes[0][0].mode == "gaming"
    assert mode_changes[0][1].mode == "gaming"
    assert guard_state == ["entered", "exited", "entered", "exited"]
    assert release_events == ["reserved", "unloaded", "released"]
    assert load_operational_mode(tmp_path).mode == "gaming"
    assert responses[-1][1]["runtime_unload"] == {
        "success": True, "backend_available": True, "unloaded": ["model-a"], "failed": {},
        "state": "complete",
    }
    assert unload_calls == [{"timeout_seconds": 3.0}]


def test_http_mode_skips_gaming_unload_after_later_resume(monkeypatch, tmp_path):
    from local_ai_hub import http_server

    unload_calls = []
    runtime = type("Runtime", (), {
        "unload_configured_models": lambda self, **kwargs: unload_calls.append(kwargs) or {"success": True},
    })()
    guard_entries = []

    class ModeGuard:
        def __enter__(self):
            guard_entries.append("entered")

        def __exit__(self, *_exc):
            guard_entries.append("exited")
            if len(guard_entries) == 2:
                set_operational_mode(tmp_path, "active")

    release_tokens = set()
    async_jobs = type("AsyncJobs", (), {
        "operational_mode_change_guard": lambda self: ModeGuard(),
        "on_operational_mode_changed": lambda self, _snapshot: None,
        "resource_release_active": lambda self: bool(release_tokens),
        "begin_resource_release": lambda self: (release_tokens.add("gaming"), "gaming")[-1],
        "end_resource_release": lambda self, token: release_tokens.discard(token),
        "wait_for_inference_actions": lambda self, _actions, _timeout: True,
        "inference_actions_active": lambda self, **_kwargs: False,
    })()
    monkeypatch.setattr(http_server, "APP", type("App", (), {
        "config": {"server": {"state_dir": str(tmp_path)}}, "runtime": runtime, "async_jobs": async_jobs,
    })())
    responses = []
    handler = type("MockHandler", (), {
        "path": "/api/admin/mode",
        "headers": {},
        "_begin_trace": lambda self, _path: None,
        "_require_authorized": lambda self: True,
        "_send": lambda self, status, payload: responses.append((status, payload)),
        "_read_json": lambda self: {"mode": "gaming"},
    })()

    http_server.Handler.do_POST(handler)

    assert responses[-1][0] == 200
    assert responses[-1][1]["success"] is False
    assert responses[-1][1]["mode_transition_stale"] is True
    assert unload_calls == []
    assert release_tokens == set()
    assert load_operational_mode(tmp_path).mode == "active"
def test_http_mode_update_rejects_invalid_and_unauthorized_requests(monkeypatch, tmp_path):
    from local_ai_hub import http_server

    monkeypatch.setattr(http_server, "APP", type("App", (), {
        "config": {"server": {"state_dir": str(tmp_path)}},
    })())
    responses = []
    handler = type("MockHandler", (), {
        "path": "/api/admin/mode",
        "headers": {},
        "_begin_trace": lambda self, _path: None,
        "_require_authorized": lambda self: True,
        "_send": lambda self, status, payload: responses.append((status, payload)),
        "_read_json": lambda self: {"mode": "paused"},
    })()

    http_server.Handler.do_POST(handler)
    assert responses[-1][0] == 400
    assert responses[-1][1]["terminal"] is True
    assert load_operational_mode(tmp_path).mode == "active"

    handler._require_authorized = lambda: False
    handler._read_json = lambda: pytest.fail("unauthorized request body must not be read")
    http_server.Handler.do_POST(handler)
    assert load_operational_mode(tmp_path).mode == "active"


def test_http_mode_update_reports_missing_async_cancellation_hook(monkeypatch, tmp_path):
    from local_ai_hub import http_server

    runtime = type("Runtime", (), {
        "unload_configured_models": lambda self, **kwargs: {
            "success": True, "backend_available": True, "unloaded": [], "failed": {},
        },
    })()
    monkeypatch.setattr(http_server, "APP", type("App", (), {
        "config": {"server": {"state_dir": str(tmp_path)}}, "runtime": runtime,
    })())
    responses = []
    handler = type("MockHandler", (), {
        "path": "/api/admin/mode",
        "headers": {},
        "_begin_trace": lambda self, _path: None,
        "_require_authorized": lambda self: True,
        "_send": lambda self, status, payload: responses.append((status, payload)),
        "_read_json": lambda self: {"mode": "maintenance"},
    })()

    http_server.Handler.do_POST(handler)

    assert responses[-1][0] == 200
    assert responses[-1][1]["success"] is True
    assert responses[-1][1]["job_cancellation"] == {
        "success": False, "error": "operational mode cancellation hook is unavailable",
    }
    assert load_operational_mode(tmp_path).mode == "maintenance"
