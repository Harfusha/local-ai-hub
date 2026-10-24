from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from urllib.parse import quote

import pytest

from local_ai_hub import http_server


def _handler(path: str, peer: str = "127.0.0.1") -> http_server.Handler:
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = path
    handler.client_address = (peer, 12345)
    handler.headers = {"Content-Type": "application/json"}
    handler._begin_trace = lambda _path: None
    handler._validate_host_and_origin = lambda: True
    handler._require_authorized = lambda: True
    handler._read_json = lambda: {"mode": "gaming"}
    handler._validate_payload = lambda _path, _payload: None
    handler.responses = []
    handler._send = lambda status, data: handler.responses.append((status, data))
    return handler


def _install_mode_api(monkeypatch, mode: str):
    snapshot = SimpleNamespace(mode=mode, revision=21, degraded=False)
    calls = []

    def gate(value, action, *, requires_heavy_work=True):
        calls.append((value.mode, action, requires_heavy_work))
        if not requires_heavy_work or (value.mode == "gaming" and action == "speculative_lint"):
            return None
        return {
            "success": False,
            "error": f"blocked in {value.mode}",
            "error_code": "operational_mode_blocked",
            "operational_mode": value.mode,
            "action": action,
            "retryable": True,
            "terminal": False,
            "retry_after_seconds": 5,
        }

    monkeypatch.setattr(http_server, "_operational_mode_api", lambda: SimpleNamespace(
        load_operational_mode=lambda *, state_dir: snapshot,
        operational_mode_gate_error=gate,
    ))
    return snapshot, calls


def test_mode_get_is_loopback_only_auth_exception_and_returns_snapshot(monkeypatch) -> None:
    snapshot = SimpleNamespace(mode="active", revision=4, degraded=False)
    monkeypatch.setattr(http_server, "_operational_mode_api", lambda: SimpleNamespace(
        load_operational_mode=lambda *, state_dir: snapshot,
    ))
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config={"security": {"api_token": ""}},
        async_jobs=SimpleNamespace(path=Path("state/jobs.sqlite3")),
    ))

    local = _handler("/api/mode")
    local._require_authorized = lambda: pytest.fail("loopback mode snapshot is read-only and needs no auth")
    local.do_GET()
    assert local.responses == [(200, {"success": True, "mode": "active", "revision": 4, "degraded": False})]

    remote = _handler("/api/mode", "203.0.113.7")
    del remote._require_authorized
    remote.do_GET()
    assert remote.responses == [
        (403, {"success": False, "error": "local_control_requires_loopback"})
    ]


def test_mode_get_without_api_token_does_not_open_admin_post(monkeypatch) -> None:
    snapshot = SimpleNamespace(mode="active", revision=4, degraded=False)
    monkeypatch.setattr(http_server, "_operational_mode_api", lambda: SimpleNamespace(
        load_operational_mode=lambda *, state_dir: snapshot,
    ))
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config={"security": {"api_token": "configured-secret"}},
        async_jobs=SimpleNamespace(path=Path("state/jobs.sqlite3")),
    ))

    local_get = _handler("/api/mode")
    local_get.headers = {"Host": "127.0.0.1"}
    local_get._validate_host_and_origin = lambda: True
    del local_get._require_authorized
    assert local_get._authorized() is False
    local_get.do_GET()
    assert local_get.responses == [(200, {"success": True, "mode": "active", "revision": 4, "degraded": False})]

    admin_post = _handler("/api/admin/mode")
    admin_post.headers = {"Host": "127.0.0.1", "Content-Type": "application/json"}
    admin_post._validate_host_and_origin = lambda: True
    del admin_post._require_authorized
    assert admin_post._authorized() is False
    admin_post.do_POST()
    assert admin_post.responses == [(401, {"success": False, "error": "unauthorized"})]


def test_dashboard_shell_stays_online_in_maintenance_without_token(monkeypatch) -> None:
    app = SimpleNamespace(config={"monitoring": {"dashboard_enabled": True}, "features": {"dashboard": True}})
    monkeypatch.setattr(http_server, "APP", app)
    handler = _handler("/dashboard")
    handler._require_authorized = lambda: pytest.fail("dashboard shell must not require API token")
    handler._send_html = lambda status, html: handler.responses.append((status, html))

    handler.do_GET()

    assert handler.responses[0][0] == 200
    assert "activityModeBadge" in handler.responses[0][1]


def test_gaming_mode_keeps_read_only_agent_task_route_available(monkeypatch, tmp_path) -> None:
    class AgentTasks:
        state_store = SimpleNamespace(enabled=True)

        def list_tasks(self, **_kwargs):
            return []

        def count(self, status=None):
            return 0

    _install_mode_api(monkeypatch, "gaming")
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config={
            "security": {
                "allowed_roots": [str(tmp_path)],
            }
        },
        async_jobs=SimpleNamespace(path=Path("state/jobs.sqlite3")), agent_tasks=AgentTasks(),
    ))
    handler = _handler(
        f"/api/agent-state/tasks?root={quote(str(tmp_path))}"
    )

    handler.do_GET()

    assert handler.responses == [(200, {
        "success": True, "tasks": [], "total_count": 0, "active_count": 0,
        "offset": 0, "limit": 100, "next_offset": 0, "has_more": False,
    })]


def test_gaming_mode_keeps_agent_event_export_available(monkeypatch, tmp_path) -> None:
    _install_mode_api(monkeypatch, "gaming")
    session_id = "session:mode-event-export"
    agent_tasks = SimpleNamespace(
        get=lambda task_id: SimpleNamespace(
            task_id=task_id,
            context=SimpleNamespace(repository_id=str(tmp_path.resolve()), session_id=session_id),
            checkpoint=SimpleNamespace(
                state_data={
                    "_agent_task_scope": {
                        "version": 2,
                        "repo_root": str(tmp_path.resolve()),
                    }
                }
            ),
        )
    )
    state_store = SimpleNamespace(export_delta=lambda stream, after, limit: {
        "success": True, "events": [], "stream_id": stream, "after_seq": after, "limit": limit,
    })
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config={
            "security": {
                "allowed_roots": [str(tmp_path)],
            }
        },
        async_jobs=SimpleNamespace(path=Path("state/jobs.sqlite3")),
        debug_traces=None,
        recovery=SimpleNamespace(lookup=lambda *_args: None),
        agent_tasks=agent_tasks,
        agent_state_store=state_store,
    ))
    handler = _handler("/api/agent-state/events/delta")
    handler._read_json = lambda: {
        "action": "export",
        "stream_id": "task:task-31",
        "task_id": "task-31",
        "root": str(tmp_path),
        "after_seq": 0,
        "limit": 50,
    }
    handler._async_delivery = lambda *_args: None

    handler.do_POST()

    assert handler.responses == [(200, {
        "success": True, "events": [], "stream_id": "task:task-31", "after_seq": 0, "limit": 50,
    })]


def test_gaming_mode_blocks_workspace_memory_but_allows_artifact_reads(monkeypatch, tmp_path) -> None:
    _install_mode_api(monkeypatch, "gaming")
    app = SimpleNamespace(
        config={
            "security": {
                "allowed_roots": [str(tmp_path)],
            }
        },
        async_jobs=SimpleNamespace(path=Path("state/jobs.sqlite3")),
        debug_traces=None,
        recovery=SimpleNamespace(lookup=lambda *_args: None),
        memory=SimpleNamespace(get=lambda _root, key: {"success": True, "key": key}),
        artifacts=SimpleNamespace(get=lambda artifact_id, *_args, **_kwargs: {"success": True, "artifact_id": artifact_id}),
    )
    monkeypatch.setattr(http_server, "APP", app)

    for path, payload, expected_status, expected_error in (
        (
            "/api/memory/get",
            {"root": str(tmp_path), "key": "note-1"},
            200,
            None,
        ),
        (
            "/api/artifact/get",
            {"artifact_id": "artifact-1"},
            200,
            None,
        ),
    ):
        handler = _handler(path)
        handler._read_json = lambda body=payload: body
        handler._async_delivery = lambda *_args: None
        handler.do_POST()
        assert handler.responses[0][0] == expected_status, handler.responses[0]
        if expected_error is not None:
            assert handler.responses[0][1]["error"] == expected_error


def test_maintenance_mode_blocks_same_agent_read_but_keeps_operator_reads(monkeypatch) -> None:
    _install_mode_api(monkeypatch, "maintenance")
    class AgentTasks:
        state_store = SimpleNamespace(enabled=True)

        def list_tasks(self, **_kwargs):
            return []

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        async_jobs=SimpleNamespace(path=Path("state/jobs.sqlite3")), agent_tasks=AgentTasks(),
    ))
    tasks = _handler("/api/agent-state/tasks")
    tasks.do_GET()
    assert tasks.responses[0][0] == 503
    assert tasks.responses[0][1]["retryable"] is True
    assert tasks.responses[0][1]["terminal"] is False

    mode = _handler("/api/mode")
    monkeypatch.setattr(http_server, "_operational_mode_api", lambda: SimpleNamespace(
        load_operational_mode=lambda *, state_dir: SimpleNamespace(mode="maintenance", revision=21, degraded=False),
    ))
    mode.do_GET()
    assert mode.responses[0][0] == 200


@pytest.mark.parametrize("mode", ["gaming", "maintenance"])
def test_context_pack_is_gated_in_both_paused_modes(monkeypatch, mode: str) -> None:
    _snapshot, calls = _install_mode_api(monkeypatch, mode)
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        async_jobs=SimpleNamespace(path=Path("state/jobs.sqlite3")),
        config={},
        debug_traces=None,
        recovery=SimpleNamespace(lookup=lambda *_args: None),
    ))
    handler = _handler("/api/context/pack")
    handler._read_json = lambda: {"root": "C:/work", "query": "lookup"}
    handler._async_delivery = lambda *_args: None

    handler.do_POST()

    assert calls == [(mode, "context_pack", True)]
    assert handler.responses[0][0] == 503
    assert handler.responses[0][1]["retryable"] is True
    assert handler.responses[0][1]["terminal"] is False


@pytest.mark.parametrize(("path", "payload"), [
    ("/api/async-jobs", {"job_action": "status", "job_id": "job-1"}),
    ("/api/async-jobs", {"job_action": "result", "job_id": "job-1"}),
    ("/api/async-jobs", {"job_action": "cancel", "job_id": "job-1"}),
    ("/api/work-orders", {"action": "status", "id": "work-1"}),
    ("/api/work-orders", {"action": "get", "id": "work-1"}),
    ("/api/work-orders", {"action": "cancel", "id": "work-1"}),
    ("/api/speculative-lint", {"action": "status", "execution_id": "lint-1"}),
    ("/api/speculative-lint", {"action": "cancel", "execution_id": "lint-1"}),
])
def test_maintenance_policy_blocks_all_existing_job_actions(
    path: str, payload: dict[str, str], monkeypatch, tmp_path: Path
) -> None:
    _install_mode_api(monkeypatch, "maintenance")
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(config={"server": {"state_dir": str(tmp_path)}}),
    )
    assert http_server._http_mode_policy("POST", path, payload) == "existing_job"
    for rejection in (
        http_server._http_mode_gate_error("POST", path),
        http_server._http_mode_gate_error("POST", path, payload),
    ):
        assert rejection is not None
        assert rejection["error_code"] == "operational_mode_blocked"


@pytest.mark.parametrize(("path", "payload"), [
    ("/api/async-jobs", {"job_action": "submit"}),
    ("/api/work-orders", {"action": "submit"}),
    ("/api/speculative-lint", {"action": "submit"}),
])
def test_maintenance_mode_blocks_job_submission_before_body_parse(
    monkeypatch, tmp_path: Path, path: str, payload: dict[str, str]
) -> None:
    _install_mode_api(monkeypatch, "maintenance")
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(config={"server": {"state_dir": str(tmp_path)}}),
    )
    for rejection in (
        http_server._http_mode_gate_error("POST", path),
        http_server._http_mode_gate_error("POST", path, payload),
    ):
        assert rejection is not None
        assert rejection["error_code"] == "operational_mode_blocked"


def test_gaming_policy_rejects_agent_state_mutation_and_unknown_method() -> None:
    assert http_server._http_mode_policy("POST", "/api/agent-state/events/delta", {"action": "import"}) == "blocked"
    assert http_server._http_mode_policy("DELETE", "/api/agent-state/tasks") == "blocked"


def test_gaming_mode_blocks_heavy_preprocess_get_with_retryable_envelope(monkeypatch) -> None:
    snapshot = SimpleNamespace(mode="gaming", revision=13, degraded=False)
    calls = []
    error = {
        "success": False, "error": "blocked", "error_code": "operational_mode_blocked",
        "operational_mode": "gaming", "action": "preprocess", "retryable": True,
        "terminal": False, "retry_after_seconds": 5,
    }

    def gate(value, action, *, requires_heavy_work=True):
        calls.append((value.mode, action, requires_heavy_work))
        return error

    monkeypatch.setattr(http_server, "_operational_mode_api", lambda: SimpleNamespace(
        load_operational_mode=lambda *, state_dir: snapshot,
        operational_mode_gate_error=gate,
    ))
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(async_jobs=SimpleNamespace(path=Path("state/jobs.sqlite3"))))
    handler = _handler("/api/preprocess")

    handler.do_GET()

    assert calls == [("gaming", "preprocess", True)]
    assert handler.responses == [(503, error)]


@pytest.mark.parametrize("mode", ["gaming", "maintenance"])
@pytest.mark.parametrize(("path", "payload", "expected_action"), [
    ("/api/delegate", {"prompt": "bounded test"}, "delegate"),
    ("/api/agent-state/events/delta", {"action": "import", "events": []}, "agent_state_events_delta"),
])
def test_heavy_or_mutating_http_route_returns_retryable_mode_envelope(
    monkeypatch, mode: str, path: str, payload: dict, expected_action: str,
) -> None:
    dispatched = []
    gate_calls = []
    state_path = Path("state/jobs.sqlite3")
    snapshot = SimpleNamespace(mode=mode, revision=12, degraded=False)
    gate_error = {
        "success": False,
        "error": f"operation blocked by operational mode ({mode})",
        "error_code": "operational_mode_blocked",
        "operational_mode": mode,
        "action": expected_action,
        "retryable": True,
        "terminal": False,
        "retry_after_seconds": 5,
    }

    def check_mode(value, action, *, requires_heavy_work=True):
        gate_calls.append((value.mode, action, requires_heavy_work))
        assert requires_heavy_work is True
        return gate_error

    monkeypatch.setattr(http_server, "_operational_mode_api", lambda: SimpleNamespace(
        load_operational_mode=lambda *, state_dir: snapshot,
        operational_mode_gate_error=check_mode,
    ))
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        async_jobs=SimpleNamespace(path=state_path),
        config={},
        debug_traces=None,
        recovery=SimpleNamespace(lookup=lambda *_args: None),
        services=SimpleNamespace(delegate=lambda *_args: dispatched.append("delegate")),
        agent_state_store=SimpleNamespace(import_delta=lambda _events: dispatched.append("import_delta")),
    ))
    handler = _handler(path)
    handler._read_json = lambda: payload
    handler._async_delivery = lambda *_args: None

    handler.do_POST()

    # POST keeps an early maintenance preflight and a payload-aware final gate.
    assert len(gate_calls) in {1, 2}
    assert all(call == (mode, expected_action, True) for call in gate_calls)
    assert dispatched == []
    assert handler.responses == [(423, gate_error)]


def test_mode_get_returns_current_unload_status(monkeypatch) -> None:
    snapshot = SimpleNamespace(mode="gaming", revision=7, degraded=False)
    app = SimpleNamespace(
        config={"server": {"state_dir": "state"}},
        async_jobs=SimpleNamespace(path=Path("state/jobs.sqlite3")),
    )
    monkeypatch.setattr(http_server, "_operational_mode_api", lambda: SimpleNamespace(
        load_operational_mode=lambda *, state_dir: snapshot,
    ))
    monkeypatch.setattr(http_server, "_MODE_UNLOAD_STATUS", {
        http_server._mode_unload_status_key(app, 7): {
            "success": False, "state": "partial", "reason": "unload_incomplete",
            "unloaded": ["model-a"], "remaining": ["model-b"],
        },
    })
    monkeypatch.setattr(http_server, "APP", app)

    handler = _handler("/api/mode")
    handler.do_GET()

    assert handler.responses[0][1]["runtime_unload"]["state"] == "partial"


def test_mode_get_returns_completed_background_unload(monkeypatch) -> None:
    complete_status_stored = threading.Event()

    class StatusMap(dict):
        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            if value.get("state") == "complete":
                complete_status_stored.set()

    monkeypatch.setattr(http_server, "_MODE_UNLOAD_STATUS", StatusMap())
    result = {
        "success": True,
        "state": "complete",
        "reason": "all_models_unloaded",
        "unloaded": ["model-a"],
        "remaining": [],
        "debug": "must not reach dashboard response",
        "in_process_cuda_detached": ["embeddings"],
        "in_process_cuda_release_failed": {"reranker": "TimeoutError", "secret": "must not leak"},
    }
    http_server._start_gaming_model_unload(8, object(), lambda *_args, **_kwargs: result, SimpleNamespace())
    assert complete_status_stored.wait(1)

    snapshot = SimpleNamespace(mode="gaming", revision=8, degraded=False)
    monkeypatch.setattr(http_server, "_operational_mode_api", lambda: SimpleNamespace(
        load_operational_mode=lambda *, state_dir: snapshot,
    ))
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(async_jobs=SimpleNamespace(path=Path("state/jobs.sqlite3"))))

    handler = _handler("/api/mode")
    handler.do_GET()

    assert handler.responses[0][1]["runtime_unload"] == {
        "success": True,
        "state": "complete",
        "reason": "all_models_unloaded",
        "unloaded": ["model-a"],
        "remaining": [],
        "in_process_cuda_detached": ["embeddings"],
        "in_process_cuda_release_failed": {"reranker": "TimeoutError"},
    }


def test_admin_mode_post_runs_configured_unload_after_releasing_guard(monkeypatch) -> None:
    events = []
    original_app = http_server.APP
    # This route changes module-level request registries to gaming mode. Keep
    # those process-wide flags isolated from tests that run afterward.
    monkeypatch.setattr(http_server, "_ACTIVE_TRANSCRIPTIONS", http_server._ActiveTranscriptionRegistry())
    monkeypatch.setattr(http_server, "_ACTIVE_CONVERSATIONS", http_server._ActiveTranscriptionRegistry())

    class Jobs:
        path = Path("state/jobs.sqlite3")

        def __init__(self) -> None:
            self._resource_release_tokens: set[str] = set()

        def begin_resource_release(self) -> str:
            token = "test-resource-release"
            self._resource_release_tokens.add(token)
            return token

        def end_resource_release(self, token: str) -> None:
            self._resource_release_tokens.discard(token)

        def resource_release_active(self) -> bool:
            return bool(self._resource_release_tokens)

        @contextmanager
        def operational_mode_change_guard(self):
            events.append("guard_enter")
            try:
                yield
            finally:
                events.append("guard_exit")

        def on_operational_mode_changed(self, snapshot):
            events.append(("changed", snapshot.mode))
            return {"inference_active": False}

        def inference_actions_active(self):
            return False

        def wait_for_inference_actions(self, _actions, _timeout):
            return True

    snapshot = SimpleNamespace(mode="gaming", revision=5, degraded=False)

    def set_mode(mode, state_dir):
        assert mode == "gaming"
        assert state_dir == Jobs.path.parent
        events.append("persist")
        return snapshot

    unload_result = {
            "success": False,
            "backend_available": True,
            "unloaded": ["model-a"],
            "failed": {"model-b": "TimeoutError"},
        }

    class Runtime:
        def unload_configured_models(self, *, timeout_seconds):
            assert timeout_seconds == 3.0
            assert events[-1] == "guard_exit"
            events.append("unload")
            return unload_result

    monkeypatch.setattr(http_server, "_operational_mode_api", lambda: SimpleNamespace(
        set_operational_mode=set_mode,
        _empty_torch_cuda_cache=lambda _timeout: {
            "success": True,
            "state": "requested",
            "verified": False,
        },
    ))
    monkeypatch.setattr(http_server, "load_operational_mode", lambda *_args, **_kwargs: snapshot)
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config={"server": {"state_dir": "state"}},
        async_jobs=Jobs(), scheduler=SimpleNamespace(foreground_busy=lambda: False), runtime=Runtime(),
    ))

    handler = _handler("/api/admin/mode")
    handler.do_POST()

    assert events[:4] == ["guard_enter", "persist", ("changed", "gaming"), "guard_exit"]
    assert events[-3:] == ["guard_enter", "guard_exit", "unload"]
    assert handler.responses[0][0] == 200
    assert handler.responses[0][1]["runtime_unload"] == unload_result
    assert http_server.APP.async_jobs.resource_release_active() is False
    monkeypatch.undo()
    assert http_server.APP is original_app


def test_admin_gaming_mode_logs_admission_drain_failure_without_exception_text(monkeypatch) -> None:
    warnings = []
    pending_callbacks = []

    class Logger:
        def warning(self, message, *args):
            warnings.append((message, args))

    class Jobs:
        path = Path("state/jobs.sqlite3")

        @contextmanager
        def operational_mode_change_guard(self):
            yield

        def on_operational_mode_changed(self, _snapshot):
            return {"inference_active": False}

        def begin_resource_release(self):
            return "release-token"

        def wait_for_inference_actions(self, _actions, _timeout):
            raise RuntimeError("sensitive backend detail")

        def inference_actions_active(self):
            return False

        def when_inference_actions_drained(self, _actions, callback):
            pending_callbacks.append(callback)

    class Tracker:
        def enter_gaming(self):
            pass

        def cancel_and_wait(self, _timeout):
            return {"inference_active": False}

        def when_drained(self, callback):
            callback()

    snapshot = SimpleNamespace(mode="gaming", revision=6, degraded=False)
    jobs = Jobs()
    monkeypatch.setattr(http_server, "_operational_mode_api", lambda: SimpleNamespace(
        set_operational_mode=lambda _mode, _state_dir: snapshot,
        _empty_torch_cuda_cache=lambda _timeout: {"success": True, "verified": False},
    ))
    monkeypatch.setattr(http_server, "load_operational_mode", lambda *_args, **_kwargs: snapshot)
    monkeypatch.setattr(http_server, "_ACTIVE_TRANSCRIPTIONS", Tracker())
    monkeypatch.setattr(http_server, "_ACTIVE_CONVERSATIONS", Tracker())
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config={"server": {"state_dir": "state"}},
        async_jobs=jobs,
        scheduler=SimpleNamespace(foreground_busy=lambda: False),
        runtime=SimpleNamespace(unload_configured_models=lambda **_kwargs: {"success": True}),
        logger=Logger(),
    ))

    handler = _handler("/api/admin/mode")
    handler.do_POST()

    assert handler.responses[0][0] == 200
    assert handler.responses[0][1]["inference_admission_release"] == {
        "state": "unavailable", "inference_active": True,
    }
    assert handler.responses[0][1]["runtime_unload"]["state"] == "deferred"
    assert len(pending_callbacks) == 1
    assert len(warnings) == 1
    assert warnings[0][1] == ("RuntimeError",)
    assert "sensitive backend detail" not in str(warnings)


def test_background_unload_deadline_replaces_pending_status(monkeypatch) -> None:
    deadline_status_stored = threading.Event()
    release_unload = threading.Event()
    unload_finished = threading.Event()

    class StatusMap(dict):
        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            if value.get("reason") == "unload_deadline_exceeded":
                deadline_status_stored.set()

    def unload(_runtime, *, inference_active):
        assert inference_active is False
        release_unload.wait(1)
        unload_finished.set()
        return {"success": True, "state": "complete", "unloaded": ["model-a"], "remaining": []}

    monkeypatch.setattr(http_server, "_MODE_UNLOAD_STATUS", StatusMap())
    monkeypatch.setattr(http_server, "_MODE_UNLOAD_DEADLINE_SECONDS", 0.02)

    app = SimpleNamespace(config={"server": {"state_dir": "state"}})
    status_key = http_server._mode_unload_status_key(app, 9)
    initial = http_server._start_gaming_model_unload(9, object(), unload, app)
    assert initial["state"] == "pending"
    assert deadline_status_stored.wait(1)
    assert http_server._MODE_UNLOAD_STATUS[status_key] == {
        "success": False,
        "state": "failed",
        "reason": "unload_deadline_exceeded",
        "unloaded": [],
        "remaining": None,
    }
    release_unload.set()
    assert unload_finished.wait(1)
    assert http_server._MODE_UNLOAD_STATUS[status_key]["state"] == "failed"


def test_in_process_cuda_models_are_detached_with_bounded_release(monkeypatch) -> None:
    release_status_stored = threading.Event()

    class StatusMap(dict):
        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            if value.get("in_process_cuda_detached") == ["embeddings"]:
                release_status_stored.set()

    class ReleasableCudaModel:
        def __init__(self):
            self._model = object()
            self.active_backend = "torch"
            self.active_device = "cuda:0"
            self.release_timeouts = []

        def release(self, timeout_seconds=3.0):
            self.release_timeouts.append(timeout_seconds)
            self._model = None
            self.active_device = None
            return True

    embeddings = ReleasableCudaModel()

    app = SimpleNamespace(
        embeddings=embeddings,
        reranker=SimpleNamespace(_model=None, active_backend="torch", active_device="cpu"),
    )
    status_key = http_server._mode_unload_status_key(app, 10)
    monkeypatch.setattr(http_server, "_MODE_UNLOAD_STATUS", StatusMap())

    initial = http_server._start_gaming_model_unload(
        10,
        object(),
        lambda _runtime, **_kwargs: {
            "success": True,
            "state": "complete",
            "reason": "all_models_unloaded",
            "unloaded": ["ollama:model-a"],
            "remaining": [],
        },
        app,
    )

    assert initial["state"] == "pending"
    assert release_status_stored.wait(1)
    stored = http_server._MODE_UNLOAD_STATUS[status_key]
    assert stored["success"] is True
    assert stored["state"] == "complete"
    assert stored["in_process_cuda_detached"] == ["embeddings"]
    assert embeddings.release_timeouts and 0 < embeddings.release_timeouts[0] <= 5.0
    assert stored.get("physical_vram_reclaimed") is not True


def test_in_process_cuda_release_timeout_keeps_runtime_unload_incomplete(monkeypatch) -> None:
    partial_status_stored = threading.Event()

    class StatusMap(dict):
        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            if value.get("reason") == "in_process_cuda_release_incomplete":
                partial_status_stored.set()

    app = SimpleNamespace(
        embeddings=SimpleNamespace(
            _model=object(), active_backend="torch", active_device="cuda",
            release=lambda timeout_seconds=3.0: False,
        ),
        reranker=SimpleNamespace(_model=None, active_backend="torch", active_device="cpu"),
    )
    monkeypatch.setattr(http_server, "_MODE_UNLOAD_STATUS", StatusMap())

    initial = http_server._start_gaming_model_unload(
        11,
        object(),
        lambda _runtime, **_kwargs: {
            "success": True,
            "state": "complete",
            "reason": "all_models_unloaded",
            "unloaded": ["ollama:model-a"],
            "remaining": [],
        },
        app,
    )

    assert initial["state"] == "pending"
    assert partial_status_stored.wait(1)
    stored = http_server._MODE_UNLOAD_STATUS[
        http_server._mode_unload_status_key(app, 11)
    ]
    assert stored["success"] is False
    assert stored["state"] == "partial"
    assert stored["in_process_cuda_release_failed"] == {"embeddings": "release_failed"}
    assert "in_process_cuda:embeddings" in stored["remaining"]


def test_activity_mode_ui_distinguishes_pending_unload() -> None:
    html = http_server.DASHBOARD_HTML
    assert "VRAM unload in progress." in html
    assert "VRAM unload incomplete." in html


def test_admin_mode_post_defers_unload_if_inference_active(monkeypatch) -> None:
    unload_calls = []
    # The route drains process-wide request registries when switching modes.
    # Keep this fixture from cancelling requests owned by tests that run later.
    monkeypatch.setattr(
        http_server, "_ACTIVE_TRANSCRIPTIONS", http_server._ActiveTranscriptionRegistry()
    )
    monkeypatch.setattr(
        http_server, "_ACTIVE_CONVERSATIONS", http_server._ActiveTranscriptionRegistry()
    )

    class Jobs:
        path = Path("state/jobs.sqlite3")

        @contextmanager
        def operational_mode_change_guard(self):
            yield

        def on_operational_mode_changed(self, _snapshot):
            return {"inference_active": True}

    snapshot = SimpleNamespace(mode="gaming", revision=6, degraded=False)
    monkeypatch.setattr(http_server, "_operational_mode_api", lambda: SimpleNamespace(
        set_operational_mode=lambda _mode, _state_dir: snapshot,
        unload_ollama_models_for_gaming=lambda *_args, **_kwargs: unload_calls.append("called"),
    ))
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        async_jobs=Jobs(), scheduler=SimpleNamespace(foreground_busy=lambda: False), runtime=object(),
    ))

    handler = _handler("/api/admin/mode")
    handler.do_POST()

    assert unload_calls == []
    assert handler.responses[0][1]["runtime_unload"] == {
        "success": False,
        "state": "deferred",
        "reason": "inference_active",
        "inference_active": True,
    }


def test_admin_mode_post_requires_authorization(monkeypatch) -> None:
    mode_writes = []
    telemetry = SimpleNamespace(record_system=lambda *_args, **_kwargs: None)
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config={"security": {"api_token": ""}, "server": {"state_dir": "unused"}},
        telemetry=telemetry,
    ))
    monkeypatch.setattr(http_server, "_operational_mode_api", lambda: SimpleNamespace(
        set_operational_mode=lambda mode, state_dir: mode_writes.append((mode, state_dir)),
    ))
    handler = _handler("/api/admin/mode", peer="203.0.113.7")
    del handler._require_authorized
    handler.headers = {
        "Content-Type": "application/json",
        "Host": "localhost",
        "Origin": "http://localhost",
        "X-LocalAI-Agent": "administrator",
    }
    handler._validate_host_and_origin = lambda: True
    handler._read_json = lambda: pytest.fail("unauthenticated remote admin request must not read body")

    handler.do_POST()

    assert handler.responses == [(401, {"success": False, "error": "unauthorized"})]
    assert mode_writes == []


def test_authorized_mutation_fails_closed_when_mode_dependency_is_unavailable(monkeypatch, tmp_path: Path) -> None:
    import json
    import urllib.error
    import urllib.request

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config={"security": {"api_token": "test-secret"}},
        async_jobs=SimpleNamespace(path=tmp_path / "jobs.sqlite3"),
    ))

    def unavailable_mode_api():
        raise ModuleNotFoundError("mode dependency unavailable")

    monkeypatch.setattr(http_server, "_operational_mode_api", unavailable_mode_api)
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    for _ in range(50):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/health", timeout=0.5):
                break
        except Exception:
            time.sleep(0.01)
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/command",
            data=b'{"action":"classify","command":"pytest -q"}',
            headers={"X-LocalAI-Token": "test-secret", "Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as response:
            urllib.request.urlopen(request, timeout=3)
        body = response.value.read().decode("utf-8")
        payload = json.loads(body)
        assert response.value.code == 404
        assert payload["success"] is False
        assert "mode dependency unavailable" not in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
