from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

import pytest


def test_t13_async_job_tracks_actual_t12_service_until_drain(tmp_path: Path):
    t13_root = Path(os.environ.get("T08_T13_WORKTREE", ""))
    t12_root = Path(os.environ.get("T08_T12_WORKTREE", ""))
    candidate_root = Path(__file__).resolve().parents[1]
    if not os.environ.get("T08_T13_WORKTREE") or not (t13_root / "src/local_ai_hub/app.py").is_file():
        pytest.skip("set T08_T13_WORKTREE to existing T13 candidate")
    if not os.environ.get("T08_T12_WORKTREE") or not (t12_root / "src/local_ai_hub/services.py").is_file():
        pytest.skip("set T08_T12_WORKTREE to existing T12 candidate")

    overlay_package = tmp_path / "overlay" / "local_ai_hub"
    overlay_package.mkdir(parents=True)
    for source_root, filename in (
        (t13_root, "app.py"),
        (t13_root, "http_server.py"),
        (t13_root, "operational_mode.py"),
        (t12_root, "services.py"),
    ):
        shutil.copyfile(
            source_root / "src/local_ai_hub" / filename,
            overlay_package / filename,
        )
    async_jobs_source = Path(
        os.environ.get(
            "T08_ASYNC_JOBS_SOURCE",
            str(candidate_root / "src/local_ai_hub/async_jobs.py"),
        )
    )
    shutil.copyfile(async_jobs_source, overlay_package / "async_jobs.py")

    script = textwrap.dedent(
        r"""
        import json, os, sys, threading, time
        from contextlib import closing
        from pathlib import Path
        from types import SimpleNamespace
        t13_src = Path(os.environ["T08_T13_WORKTREE"]) / "src"
        t12_src = Path(os.environ["T08_T12_WORKTREE"]) / "src"
        candidate_src = Path(os.environ["T08_CANDIDATE_WORKTREE"]) / "src"
        overlay_pkg = Path(os.environ["T08_OVERLAY_PACKAGE"])
        sys.path[:0] = [str(t13_src), str(t12_src), str(candidate_src)]
        import local_ai_hub
        local_ai_hub.__path__[:] = [
            str(overlay_pkg),
            str(t13_src / "local_ai_hub"),
            str(t12_src / "local_ai_hub"),
            str(candidate_src / "local_ai_hub"),
        ]
        from types import SimpleNamespace
        from local_ai_hub.app import LocalAIApp
        from local_ai_hub.artifacts import ArtifactStore
        from local_ai_hub.async_jobs import AsyncJobManager
        from local_ai_hub.conversations import ConversationStore
        from local_ai_hub import http_server
        from local_ai_hub.operational_mode import set_operational_mode
        from local_ai_hub.services import LocalAIServices

        state_dir = Path(os.environ["T08_STATE_DIR"])
        state_dir.mkdir(parents=True, exist_ok=True)
        set_operational_mode(state_dir, "active")
        service = object.__new__(LocalAIServices)
        service.config = {"model_conversations": {"max_prompt_tokens": 8192}}
        service.conversations = ConversationStore(idle_ttl_seconds=60)
        service.router = SimpleNamespace(
            classify=lambda *_args, **_kwargs: {
                "model": "test-model", "task_type": "general", "complexity": "normal"
            },
            apply_model_override=lambda route, _model: route,
        )
        service._resident_optimize = lambda route, *_args, **_kwargs: route
        service._resolve_local_task_project = lambda _root: (None, "", "", "")
        entered = [threading.Event(), threading.Event()]
        release = threading.Event()
        call_count = []
        call_lock = threading.Lock()
        def controlled_model_boundary(*_args, **_kwargs):
            with call_lock:
                index = len(call_count)
                call_count.append("generate")
            if index >= len(entered):
                raise AssertionError("unexpected extra model boundary call")
            entered[index].set()
            if not release.wait(8):
                raise TimeoutError("controlled inference release timed out")
            return {"success": True, "text": "controlled result", "model": "test-model"}
        service._generate = controlled_model_boundary

        app = object.__new__(LocalAIApp)
        app.services = service
        config = {
            "server": {"state_dir": str(state_dir), "bind": "127.0.0.1"},
            "security": {"api_token": ""},
            "async_jobs": {"enabled": True, "result_ttl_seconds": 3600},
            "artifacts": {"ttl_hours": 1},
            "model_conversations": {"max_prompt_tokens": 8192},
        }
        artifacts = ArtifactStore(state_dir, ttl_hours=1)
        manager = AsyncJobManager(config, None, artifacts, None)
        app.async_jobs = manager
        manager.executor = app._execute_async_task
        app.config = config
        class Runtime:
            config = {"ollama": {"enabled": True}}
            def __init__(self):
                self.unload_calls = []
            def unload_configured_models(self, **kwargs):
                self.unload_calls.append(dict(kwargs))
                raise AssertionError("Ollama unload ran while inference was active")
        app.runtime = Runtime()
        app.preprocessor = None
        app.embeddings = None
        app.reranker = None
        app.debug_traces = None
        class Telemetry:
            @staticmethod
            def record_system(*_args, **_kwargs):
                return None
            @staticmethod
            def record_error(*_args, **_kwargs):
                return None
        app.telemetry = Telemetry()
        class Recovery:
            @staticmethod
            def fingerprint_payload(_payload):
                return "controlled-fingerprint"
            @staticmethod
            def begin(*_args, **_kwargs):
                return {"claimed": True, "state": "running", "response": None}
            @staticmethod
            def finish(*_args, **_kwargs):
                return None
        app.recovery = Recovery()
        http_server.APP = app
        http_server._GAMING_DRAIN_TIMEOUT_SECONDS = 0.1
        http_server.Handler._begin_trace = lambda self, path: setattr(self, "_trace_request_id", f"req-{path}")
        http_server.Handler._validate_host_and_origin = lambda _self: True
        http_server.Handler._tenant_binding_allowed = lambda _self: True
        http_server.Handler._validate_payload = lambda _self, _path, _payload: None
        http_server.Handler._read_json = lambda self: self._test_payload
        http_server.Handler._tenant = lambda _self: "tenant-a"
        http_server.Handler._agent = lambda _self: "test-agent"

        def make_handler(path, payload):
            handler = object.__new__(http_server.Handler)
            handler.path = path
            handler.command = "POST"
            handler.headers = {"Content-Type": "application/json", "Host": "localhost"}
            handler.client_address = ("127.0.0.1", 12345)
            handler.server = SimpleNamespace()
            handler._test_payload = payload
            responses = []
            handler._send = lambda status, data: responses.append((status, data))
            return handler, responses

        initial = service.conversations.start("tenant-a", {
            "model": "test-model", "system": "controlled system", "max_tokens": 64,
            "temperature": 0.0, "source": "test", "priority": 1,
            "route": {"model": "test-model", "task_type": "general", "complexity": "normal"},
            "trace_system": "controlled system",
        })
        drained = threading.Event()
        http_done = threading.Event()
        try:
            submitted = manager.submit(
                "tenant-a", "delegate", {"task": "controlled test"}
            )
            assert submitted.get("success") is True, submitted
            job_id = submitted["job_id"]
            assert entered[0].wait(8), "T12 LocalAIServices.delegate did not reach controlled model boundary"
            row = manager._row("tenant-a", job_id)
            assert row is not None and row["state"] == "running"
            assert manager.inference_actions_active() is True
            manager.when_inference_actions_drained({"delegate"}, drained.set)

            conversation_handler, conversation_responses = make_handler(
                "/api/conversations/continue",
                {"conversation_id": initial.conversation_id, "task": "continue while async worker is active"},
            )
            conversation_thread = threading.Thread(
                target=lambda: (http_server.Handler.do_POST(conversation_handler), http_done.set()),
                daemon=True,
            )
            conversation_thread.start()
            assert entered[1].wait(8), "T12 LocalAIServices.continue_conversation did not reach controlled model boundary"
            assert manager.inference_actions_active() is True
            assert not drained.wait(0.05), "drain callback fired while async and HTTP conversation services were active"

            mode_handler, mode_responses = make_handler("/api/admin/mode", {"mode": "gaming"})
            http_server.Handler.do_POST(mode_handler)
            assert mode_responses and mode_responses[0][0] == 200, mode_responses
            mode_receipt = mode_responses[0][1]
            assert mode_receipt.get("mode_changed") is True, mode_receipt
            assert mode_receipt.get("transition", {}).get("inference_active") is True, mode_receipt
            assert mode_receipt.get("resources", {}).get("conversation_release", {}).get("state") == "timed_out", mode_receipt
            assert mode_receipt.get("resources", {}).get("inference_admission_release", {}).get("state") == "timed_out", mode_receipt
            assert app.runtime.unload_calls == [], "GPU-backed runtime unload must be deferred while consumers are active"
            assert manager.resource_release_active() is True
            assert not drained.is_set(), "drain callback fired before active services returned"

            blocked = manager.submit(
                "tenant-a", "delegate", {"task": "must not dispatch while gaming"}
            )
            assert blocked.get("success") is False, blocked
            with closing(manager._connect()) as con:
                persisted_rows = int(con.execute("SELECT COUNT(*) FROM async_jobs").fetchone()[0])
            assert persisted_rows == 1, persisted_rows
            assert len(call_count) == 2, call_count
            assert manager.inference_actions_active() is True

            release.set()
            assert drained.wait(8), "drain callback did not fire after T12 service exit"
            conversation_thread.join(8)
            assert not conversation_thread.is_alive(), "HTTP conversation handler did not finish"
            assert http_done.is_set(), "HTTP conversation handler exited without completion"
            assert conversation_responses and conversation_responses[0][0] == 200, conversation_responses
            deadline = time.monotonic() + 3
            while manager.resource_release_active() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert manager.resource_release_active() is False, "resource release ownership did not end after all consumers drained"
            final = manager.wait("tenant-a", job_id, 8)
            assert final.get("terminal") is True, final
            assert manager.inference_actions_active() is False
            print(json.dumps({
                "job_id": job_id,
                "final_state": final.get("state"),
                "drain_callback_after_service_exit": drained.is_set(),
                "http_conversation_status": conversation_responses[0][0],
                "mode_release_deferred_while_active": mode_receipt.get("resources", {}).get("inference_admission_release", {}).get("state"),
                "persisted_rows": persisted_rows,
                "model_boundary_calls": len(call_count),
            }))
        finally:
            release.set()
            manager.close()
        """
    )
    env = os.environ.copy()
    env.update(
        {
            "T08_T13_WORKTREE": str(t13_root),
            "T08_T12_WORKTREE": str(t12_root),
            "T08_CANDIDATE_WORKTREE": str(candidate_root),
            "T08_OVERLAY_PACKAGE": str(overlay_package),
            "T08_STATE_DIR": str(tmp_path / "state"),
            "PYTHONPATH": os.pathsep.join(
                (
                    str(t13_root / "src"),
                    str(t12_root / "src"),
                    str(candidate_root / "src"),
                )
            ),
        }
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=candidate_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads(result.stdout.strip().splitlines()[-1])
    assert receipt["drain_callback_after_service_exit"] is True
    assert receipt["persisted_rows"] == 1
    assert receipt["model_boundary_calls"] == 2
    assert receipt["http_conversation_status"] == 200
    assert receipt["mode_release_deferred_while_active"] == "timed_out"
