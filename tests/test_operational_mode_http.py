from __future__ import annotations

from contextlib import contextmanager
import threading
from types import SimpleNamespace

import pytest

from local_ai_hub import http_server, operational_mode


@pytest.fixture(autouse=True)
def _fresh_cancellable_registries(monkeypatch):
    monkeypatch.setattr(http_server, "_ACTIVE_TRANSCRIPTIONS", http_server._ActiveTranscriptionRegistry())
    monkeypatch.setattr(http_server, "_ACTIVE_CONVERSATIONS", http_server._ActiveTranscriptionRegistry())


class _Recovery:
    def lookup(self, *_args, **_kwargs):
        return None

    def begin(self, *_args, **_kwargs):
        return {"claimed": True, "state": "running", "response": None}

    @staticmethod
    def fingerprint_payload(_payload):
        return "test-fingerprint"


class _ModeManager:
    def __init__(self, state_dir=None, *, inference_active=False):
        self.state_dir = state_dir
        self.inference_active = inference_active
        self.snapshots = []
        self.resource_release_tokens = set()
        self.mode_change_guard_active = False
        self.release_guard_states = []
        self.drain_callbacks = []

    @contextmanager
    def operational_mode_change_guard(self):
        self.mode_change_guard_active = True
        try:
            yield
        finally:
            self.mode_change_guard_active = False

    def on_operational_mode_changed(self, snapshot):
        self.snapshots.append(snapshot)
        return {"success": True, "inference_active": self.inference_active}

    def foreground_busy(self):
        return self.inference_active or bool(self.resource_release_tokens)

    def inference_actions_active(self, *, exclude_actions=frozenset()):
        return self.inference_active

    def wait_for_inference_actions(self, _actions, _timeout_seconds):
        return not self.inference_active

    def when_inference_actions_drained(self, _actions, callback):
        if self.inference_active:
            self.drain_callbacks.append(callback)
        else:
            callback()

    def begin_resource_release(self):
        self.release_guard_states.append(self.mode_change_guard_active)
        token = str(len(self.resource_release_tokens) + 1)
        self.resource_release_tokens.add(token)
        return token

    def resource_release_active(self):
        return bool(self.resource_release_tokens)

    def end_resource_release(self, token):
        self.resource_release_tokens.discard(token)

    @contextmanager
    def inference_admission(self, action):
        snapshot = operational_mode.load_operational_mode(self.state_dir)
        rejection = operational_mode.operational_mode_gate_error(snapshot, action)
        if rejection is not None:
            rejection["status_code"] = 423
        yield rejection


class _OllamaRuntime:
    config = {"ollama": {"enabled": True}}

    def __init__(self, names):
        self.names = list(names)
        self.unload_calls = []

    def unload_configured_models(self, *, timeout_seconds, should_stop=None, deadline=None):
        self.unload_calls.extend(self.names)
        unloaded = list(self.names)
        self.names.clear()
        return {"success": True, "unloaded": unloaded, "remaining": [], "verified": True}


def _handler(monkeypatch, tmp_path, *, method, path, payload=None, peer="127.0.0.1", auth_token="test-mode-token", manager=None, runtime=None):
    responses = []
    app = SimpleNamespace(
        config={"server": {"state_dir": str(tmp_path), "bind": "127.0.0.1"}, "security": {"api_token": "test-mode-token"}},
        async_jobs=manager or _ModeManager(tmp_path),
        runtime=runtime or _OllamaRuntime(["fast:latest"]),
        recovery=_Recovery(),
        debug_traces=None,
        telemetry=SimpleNamespace(record_system=lambda *_args, **_kwargs: None),
    )
    if manager is not None:
        manager.state_dir = tmp_path
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server.Handler, "_begin_trace", lambda self, _path: setattr(self, "_trace_request_id", "req-mode"))
    monkeypatch.setattr(http_server.Handler, "_validate_host_and_origin", lambda _self: True)
    monkeypatch.setattr(http_server.Handler, "_agent", lambda _self: "agent")
    if method == "POST":
        monkeypatch.setattr(http_server.Handler, "_read_json", lambda _self: payload or {})
    handler = object.__new__(http_server.Handler)
    handler._send = lambda status, data: responses.append((status, data))
    handler.path = path
    handler.command = method
    handler.headers = {
        "Content-Type": "application/json",
        "Host": "localhost",
    }
    if auth_token is not None:
        handler.headers["X-LocalAI-Token"] = auth_token
    handler.client_address = (peer, 1000)
    handler.server = SimpleNamespace()
    return handler, app, responses


def test_get_mode_returns_persisted_snapshot_for_loopback(monkeypatch, tmp_path):
    operational_mode.set_operational_mode(tmp_path, "gaming")
    handler, _app, responses = _handler(monkeypatch, tmp_path, method="GET", path="/api/mode")

    http_server.Handler.do_GET(handler)

    status, response = responses[0]
    assert status == 200
    assert response["success"] is True
    assert response["mode"] == "gaming"
    assert response["revision"] == 1


def test_get_mode_is_available_to_loopback_dashboard_without_token(monkeypatch, tmp_path):
    handler, _app, responses = _handler(
        monkeypatch, tmp_path, method="GET", path="/api/mode", auth_token=None
    )

    http_server.Handler.do_GET(handler)

    assert responses[0][0] == 200
    assert responses[0][1]["success"] is True
    assert responses[0][1]["mode"] == "active"


def test_admin_mode_control_remains_available_in_maintenance(monkeypatch, tmp_path):
    operational_mode.set_operational_mode(tmp_path, "maintenance")
    handler, _app, responses = _handler(
        monkeypatch, tmp_path, method="POST", path="/api/admin/mode", payload={"mode": "active"}
    )

    http_server.Handler.do_POST(handler)

    assert responses[-1][0] == 200
    assert responses[-1][1]["mode_changed"] is True
    assert operational_mode.load_operational_mode(tmp_path).mode == "active"


def test_gaming_cleanup_runs_outside_mode_guard_and_keeps_release_reserved(monkeypatch, tmp_path):
    class LockingManager(_ModeManager):
        def __init__(self, state_dir):
            super().__init__(state_dir)
            self.mode_lock = threading.Lock()

        @contextmanager
        def operational_mode_change_guard(self):
            with self.mode_lock:
                self.mode_change_guard_active = True
                try:
                    yield
                finally:
                    self.mode_change_guard_active = False

    unload_entered = threading.Event()
    finish_unload = threading.Event()

    class BlockingRuntime(_OllamaRuntime):
        def unload_configured_models(self, *, timeout_seconds, should_stop=None, deadline=None):
            assert manager.mode_change_guard_active is False
            unload_entered.set()
            assert finish_unload.wait(2)
            return super().unload_configured_models(
                timeout_seconds=timeout_seconds, should_stop=should_stop, deadline=deadline
            )

    manager = LockingManager(tmp_path)
    runtime = BlockingRuntime(["fast:latest"])
    handler, _app, responses = _handler(
        monkeypatch, tmp_path, method="POST", path="/api/admin/mode",
        payload={"mode": "gaming"}, manager=manager, runtime=runtime,
    )
    transition = threading.Thread(target=http_server.Handler.do_POST, args=(handler,), daemon=True)
    transition.start()

    try:
        assert unload_entered.wait(1)
        assert manager.resource_release_active() is True
        assert manager.mode_lock.acquire(timeout=0.1) is True
        manager.mode_lock.release()

        resume_handler, _app, resume_responses = _handler(
            monkeypatch, tmp_path, method="POST", path="/api/admin/mode",
            payload={"mode": "active"}, manager=manager, runtime=runtime,
        )
        http_server.Handler.do_POST(resume_handler)
        assert resume_responses[-1][0] == 423
        assert resume_responses[-1][1]["error_code"] == "resource_release_in_progress"
        assert manager.resource_release_active() is True
    finally:
        finish_unload.set()
        transition.join(2)

    assert not transition.is_alive()
    assert responses[-1][0] == 200
    assert manager.resource_release_active() is False


@pytest.mark.parametrize(
    ("path", "payload", "expected_call"),
    [
        ("/api/async-jobs", {"action": "status", "job_id": "job-1"}, "status"),
        ("/api/async-jobs", {"action": "wait", "job_id": "job-1", "timeout_seconds": 0}, "wait"),
        ("/api/async-jobs", {"action": "result", "job_id": "job-1"}, "result"),
        ("/api/async-jobs", {"action": "cancel", "job_id": "job-1"}, "cancel"),
        ("/api/evaluation", {"action": "report"}, "evaluation_report"),
        ("/api/repo/profile", {"root": "C:/repo"}, "repo_profile"),
    ],
)
@pytest.mark.parametrize("mode", ["maintenance", "gaming"])
def test_safe_agent_api_reads_block_only_in_maintenance_before_database_call(
    monkeypatch, tmp_path, path, payload, expected_call, mode
):
    calls = []
    if path == "/api/repo/profile":
        payload = {
            **payload,
            "root": str(tmp_path),
        }

    class JobControls:
        state_dir = tmp_path
        def status(self, *_args): calls.append("status"); return {"success": True}
        def wait(self, *_args): calls.append("wait"); return {"success": True}
        def result(self, *_args): calls.append("result"); return {"success": True}
        def cancel(self, *_args): calls.append("cancel"); return {"success": True}

    operational_mode.set_operational_mode(tmp_path, mode)
    handler, app, responses = _handler(
        monkeypatch, tmp_path, method="POST", path=path, payload=payload, manager=JobControls()
    )
    if path == "/api/repo/profile":
        app.config["security"].update(
            allowed_roots=[str(tmp_path)],
        )
    trace_calls = []
    monkeypatch.setattr(http_server.Handler, "_begin_trace", lambda _self, trace_path: trace_calls.append(trace_path))
    app.services = SimpleNamespace(
        evaluation=lambda _payload: calls.append("evaluation_report") or {"success": True},
        repo_profile=lambda _root: calls.append("repo_profile") or {"success": True},
    )

    http_server.Handler.do_POST(handler)

    status, response = responses[-1]
    if mode == "maintenance":
        assert status == 423
        assert response["error_code"] == "operational_mode_blocked"
        assert calls == []
        assert trace_calls == []
    else:
        assert status == 200
        assert calls == [expected_call]
        assert trace_calls == [path]


def test_mode_api_rejects_non_loopback_peer(monkeypatch, tmp_path):
    handler, _app, responses = _handler(
        monkeypatch, tmp_path, method="GET", path="/api/mode", peer="192.0.2.10"
    )

    http_server.Handler.do_GET(handler)

    assert responses[0][0] == 403
    assert responses[0][1]["error"] == "local_control_requires_loopback"


def test_mode_api_obeys_configured_api_token(monkeypatch):
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config={"security": {"api_token": "local-secret"}}
    ))
    handler = object.__new__(http_server.Handler)
    handler.headers = {}

    assert http_server.Handler._authorized(handler) is False
    handler.headers = {"X-LocalAI-Token": "local-secret"}
    assert http_server.Handler._authorized(handler) is True


def test_post_admin_mode_accepts_authorized_non_loopback_peer(monkeypatch, tmp_path):
    handler, _app, responses = _handler(
        monkeypatch, tmp_path, method="POST", path="/api/admin/mode",
        payload={"mode": "gaming"}, peer="192.0.2.10",
    )

    http_server.Handler.do_POST(handler)

    assert responses[0][0] == 200
    assert responses[0][1]["mode"] == "gaming"
    assert operational_mode.load_operational_mode(tmp_path).mode == "gaming"


def test_post_admin_mode_requires_api_token(monkeypatch, tmp_path):
    handler, _app, responses = _handler(
        monkeypatch, tmp_path, method="POST", path="/api/admin/mode",
        payload={"mode": "gaming"}, auth_token=None,
    )

    http_server.Handler.do_POST(handler)

    assert responses[0][0] == 401
    assert responses[0][1]["error"] == "unauthorized"
    assert operational_mode.load_operational_mode(tmp_path).mode == "active"


def test_post_mode_rejects_invalid_mode_without_persisting(monkeypatch, tmp_path):
    handler, _app, responses = _handler(
        monkeypatch, tmp_path, method="POST", path="/api/admin/mode",
        payload={"mode": "turbo"},
    )

    http_server.Handler.do_POST(handler)

    assert responses[0][0] == 400
    assert operational_mode.load_operational_mode(tmp_path).mode == "active"


def test_sync_inference_http_gate_retries(
    monkeypatch, tmp_path
):
    operational_mode.set_operational_mode(tmp_path, "gaming")
    handler, _app, responses = _handler(
        monkeypatch, tmp_path, method="POST", path="/api/reason",
        payload={"problem": "reason about this"},
    )

    http_server.Handler.do_POST(handler)

    status, response = responses[-1]
    assert status == 423
    assert response["terminal"] is False
    assert response["retryable"] is True
    assert 0 < response["retry_after_seconds"] <= 10


@pytest.mark.parametrize(
    ("mode", "path"),
    [
        ("gaming", "/api/generate"),
        ("gaming", "/api/chat"),
        ("maintenance", "/api/generate"),
        ("maintenance", "/api/chat"),
    ],
)
def test_raw_ollama_proxy_inference_is_blocked_in_restricted_mode(
    monkeypatch, tmp_path, mode, path
):
    operational_mode.set_operational_mode(tmp_path, mode)
    proxy_calls = []
    handler, app, responses = _handler(
        monkeypatch,
        tmp_path,
        method="POST",
        path=path,
        payload={"model": "fast:latest", "prompt": "must be blocked"},
    )
    app.services = SimpleNamespace(
        proxy_request=lambda *args: proxy_calls.append(args) or {"response": "unexpected"}
    )

    http_server.Handler.do_POST(handler)

    status, response = responses[-1]
    assert status == 423
    assert response["error_code"] == "operational_mode_blocked"
    assert proxy_calls == []


@pytest.mark.parametrize("inference_active", [False, True])
def test_post_gaming_persists_mode_reports_transition_and_unload(
    monkeypatch, tmp_path, inference_active
):
    manager = _ModeManager(inference_active=inference_active)
    runtime = _OllamaRuntime(["fast:latest", "reasoner:7b"])
    handler, _app, responses = _handler(
        monkeypatch, tmp_path, method="POST", path="/api/admin/mode",
        payload={"mode": "gaming"}, manager=manager, runtime=runtime,
    )

    http_server.Handler.do_POST(handler)

    status, response = responses[-1]
    assert status == 200
    assert response["mode_changed"] is True
    assert response["mode"] == "gaming"
    assert response["revision"] == 1
    assert response["resources"]["in_process_cuda_release"]["state"] in {
        "not_applicable", "released", "deferred"
    }
    assert response["resources"]["in_process_cuda_release"]["verified"] is False
    assert response["resources"]["whisper_process_release"]["state"] == "not_applicable"
    assert len(manager.snapshots) == 1
    if inference_active:
        assert response["unload"]["state"] == "deferred"
        assert runtime.unload_calls == []
    else:
        assert response["unload"]["state"] == "complete"
        assert runtime.unload_calls == ["fast:latest", "reasoner:7b"]
    if inference_active:
        assert manager.resource_release_tokens
        assert manager.drain_callbacks
    else:
        assert manager.resource_release_tokens == set()
    assert operational_mode.load_operational_mode(tmp_path).mode == "gaming"

    status_handler, _status_app, status_responses = _handler(
        monkeypatch, tmp_path, method="GET", path="/api/mode", manager=manager, runtime=runtime,
    )
    http_server.Handler.do_GET(status_handler)
    status, current = status_responses[-1]
    assert status == 200
    assert current["runtime_unload"]["state"] == response["unload"]["state"]
    assert current["runtime_unload"]["success"] is response["unload"]["success"]


def test_post_gaming_reserves_release_before_exposing_mode_change(
    monkeypatch, tmp_path
):
    manager = _ModeManager()
    handler, _app, responses = _handler(
        monkeypatch, tmp_path, method="POST", path="/api/admin/mode",
        payload={"mode": "gaming"}, manager=manager,
    )

    http_server.Handler.do_POST(handler)

    assert responses[-1][0] == 200
    assert manager.release_guard_states == [True]
    assert manager.resource_release_tokens == set()


def test_post_active_defers_while_accelerator_release_owns_resources(
    monkeypatch, tmp_path
):
    manager = _ModeManager()
    release_token = manager.begin_resource_release()
    operational_mode.set_operational_mode(tmp_path, "gaming")
    handler, _app, responses = _handler(
        monkeypatch, tmp_path, method="POST", path="/api/admin/mode",
        payload={"mode": "active"}, manager=manager,
    )

    http_server.Handler.do_POST(handler)

    status, response = responses[-1]
    assert status == 423
    assert response["error_code"] == "resource_release_in_progress"
    assert response["mode_changed"] is False
    assert response["mode"] == "gaming"
    assert operational_mode.load_operational_mode(tmp_path).mode == "gaming"
    manager.end_resource_release(release_token)


def test_post_gaming_defers_in_process_release_for_running_preprocess(monkeypatch, tmp_path):
    class ResidentModel:
        calls = 0

        def status(self):
            return {"loaded": True, "active_backend": "torch", "active_device": "cuda:0"}

        def release(self, timeout_seconds=3.0):
            self.calls += 1
            return True

    handler, app, responses = _handler(
        monkeypatch, tmp_path, method="POST", path="/api/admin/mode",
        payload={"mode": "gaming"}, manager=_ModeManager(),
    )
    app.embeddings = ResidentModel()
    app.preprocessor = SimpleNamespace(
        status=lambda: {"success": True, "projects": [{"status": "running"}]}
    )

    http_server.Handler.do_POST(handler)

    status, response = responses[-1]
    assert status == 200
    assert response["transition"]["preprocessing_active"] is True
    assert response["resources"]["in_process_cuda_release"]["state"] == "deferred"
    assert app.embeddings.calls == 0


def test_post_gaming_reports_mocked_cuda_cleanup(monkeypatch, tmp_path):
    class ResidentModel:
        def status(self):
            return {
                "loaded": getattr(self, "loaded", True),
                "active_backend": "torch",
                "active_device": "cuda:0",
                "cache_cleanup": {"success": True, "state": "requested", "verified": False},
            }

        def release(self, timeout_seconds=3.0):
            assert 0 < timeout_seconds <= operational_mode._IN_PROCESS_RELEASE_DEADLINE_SECONDS
            self.loaded = False
            return True

    cleanup = []
    monkeypatch.setattr(
        operational_mode,
        "_empty_torch_cuda_cache",
        lambda timeout, **_kwargs: cleanup.append(timeout) or {"success": True, "state": "requested", "verified": False},
    )
    handler, app, responses = _handler(
        monkeypatch, tmp_path, method="POST", path="/api/admin/mode",
        payload={"mode": "gaming"}, manager=_ModeManager(),
    )
    app.embeddings = ResidentModel()

    http_server.Handler.do_POST(handler)

    status, response = responses[-1]
    assert status == 200
    assert response["resources"]["in_process_cuda_release"]["state"] == "complete"
    assert response["resources"]["in_process_cuda_release"]["cuda_cleanup"]["state"] == "requested"
    assert response["resources"]["in_process_cuda_release"]["verified"] is False
    assert cleanup == []


def test_gaming_cancels_active_whisper_before_unload_and_blocks_new_transcriptions(monkeypatch, tmp_path):
    import threading

    manager = _ModeManager()
    runtime = _OllamaRuntime(["fast:latest"])
    _ACTIVE = http_server._ACTIVE_TRANSCRIPTIONS
    _ACTIVE.enter_active()
    calls = []
    started = threading.Event()

    def transcribe(_payload, *, cancel_event):
        calls.append(cancel_event)
        started.set()
        assert cancel_event.wait(timeout=2.0)
        return {"success": False, "reason": "cancelled", "cancelled": True}

    request_handler, app, request_responses = _handler(
        monkeypatch, tmp_path, method="POST", path="/api/task/transcribe", payload={"audio": "voice.wav"}, manager=manager,
    )
    app.runtime = runtime
    app.services = SimpleNamespace(transcribe=transcribe)
    request_thread = threading.Thread(target=http_server.Handler.do_POST, args=(request_handler,))
    request_thread.start()
    assert started.wait(timeout=1.0)

    admin_handler, _admin_app, admin_responses = _handler(
        monkeypatch, tmp_path, method="POST", path="/api/admin/mode", payload={"mode": "gaming"}, manager=manager,
    )
    monkeypatch.setattr(http_server, "APP", app)
    http_server.Handler.do_POST(admin_handler)
    request_thread.join(timeout=1.0)

    assert not request_thread.is_alive()
    assert request_responses[-1][1]["reason"] == "cancelled"
    status, response = admin_responses[-1]
    assert status == 200
    assert response["resources"]["whisper_process_release"]["state"] == "cancelled"
    assert response["resources"]["ollama_unload"]["state"] == "complete"
    assert runtime.unload_calls == ["fast:latest"]

    new_handler, _new_app, new_responses = _handler(
        monkeypatch, tmp_path, method="POST", path="/api/task/transcribe", payload={"audio": "later.wav"}, manager=manager,
    )
    monkeypatch.setattr(http_server, "APP", app)
    http_server.Handler.do_POST(new_handler)
    assert new_responses[-1][0] == 423
    assert len(calls) == 1


def test_transcription_timeout_keeps_resource_token_until_worker_returns():
    registry = http_server._ActiveTranscriptionRegistry()
    token, _event = registry.begin()
    registry.enter_gaming()
    drained = []
    receipt = registry.cancel_and_wait(0.01)
    registry.when_drained(lambda: drained.append(True))

    assert receipt["state"] == "timed_out"
    assert receipt["inference_active"] is True
    assert drained == []
    registry.finish(token, {"success": False, "reason": "cancelled", "cancelled": True})
    assert drained == [True]
    assert registry.cancel_and_wait(0.01)["state"] == "not_applicable"


def test_gaming_fails_closed_when_admission_tracking_is_unavailable(monkeypatch, tmp_path):
    manager = _ModeManager(tmp_path, inference_active=True)
    manager.inference_actions_active = None
    manager.wait_for_inference_actions = None
    manager.when_inference_actions_drained = None
    runtime = _OllamaRuntime(["fast:latest"])
    handler, _app, responses = _handler(
        monkeypatch,
        tmp_path,
        method="POST",
        path="/api/admin/mode",
        payload={"mode": "gaming"},
        manager=manager,
        runtime=runtime,
    )

    http_server.Handler.do_POST(handler)

    response = responses[-1][1]
    assert response["resources"]["inference_admission_release"]["state"] == "unavailable"
    assert response["resources"]["whisper_process_release"]["state"] == "not_applicable"
    assert response["success"] is False
    assert runtime.unload_calls == []
    assert manager.resource_release_tokens


def test_gaming_keeps_release_token_when_whisper_cleanup_is_unverified(monkeypatch, tmp_path):
    from local_ai_hub import process_utils

    registry = http_server._ActiveTranscriptionRegistry()
    monkeypatch.setattr(http_server, "_ACTIVE_TRANSCRIPTIONS", registry)
    monkeypatch.setattr(http_server, "_GAMING_DRAIN_TIMEOUT_SECONDS", 0.01, raising=False)
    manager = _ModeManager(tmp_path)
    runtime = _OllamaRuntime(["fast:latest"])
    live_process = SimpleNamespace(poll=lambda: None)
    cleanup_error = process_utils.ProcessCleanupUnverifiedError(
        ["whisper"], process=live_process, tree_termination_confirmed=False
    )
    transcribe_handler, app, transcribe_responses = _handler(
        monkeypatch,
        tmp_path,
        method="POST",
        path="/api/task/transcribe",
        payload={"audio": "voice.wav"},
        manager=manager,
        runtime=runtime,
    )
    app.services = SimpleNamespace(transcribe=lambda *_args, **_kwargs: (_ for _ in ()).throw(cleanup_error))

    http_server.Handler.do_POST(transcribe_handler)
    assert transcribe_responses[-1][0] == 503
    assert registry.cancel_and_wait(0.0)["state"] == "timed_out"

    admin_handler, admin_app, admin_responses = _handler(
        monkeypatch,
        tmp_path,
        method="POST",
        path="/api/admin/mode",
        payload={"mode": "gaming"},
        manager=manager,
        runtime=runtime,
    )
    admin_app.services = app.services
    monkeypatch.setattr(http_server, "APP", admin_app)
    http_server.Handler.do_POST(admin_handler)

    response = admin_responses[-1][1]
    assert response["resources"]["whisper_process_release"]["state"] == "timed_out"
    assert response["success"] is False
    assert runtime.unload_calls == []
    assert manager.resource_release_tokens


def test_unverified_whisper_cleanup_keeps_registry_active(monkeypatch):
    registry = http_server._ActiveTranscriptionRegistry()
    token, _event = registry.begin()
    registry.defer_process_cleanup(
        token,
        SimpleNamespace(wait=lambda: None),
        tree_termination_confirmed=False,
    )

    assert registry.cancel_and_wait(0.0)["state"] == "timed_out"
