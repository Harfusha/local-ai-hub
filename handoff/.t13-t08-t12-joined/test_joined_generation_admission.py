from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap


T13 = Path(__file__).resolve().parents[2]
T08 = Path(r"C:\Users\Adam\.codex\worktrees\t08-agent-os\.local-ai-hub")
T12 = Path(r"C:\Users\Adam\.codex\worktrees\4816\.local-ai-hub")
T12_STAGE = T12 / "handoff/.t12-r7-generation-boundary/overlay"


def test_async_job_rechecks_t12_generation_admission_after_gaming(tmp_path: Path) -> None:
    assert (T08 / "src/local_ai_hub/async_jobs.py").is_file()
    assert (T12_STAGE / "src/local_ai_hub/services.py").is_file()
    package = tmp_path / "overlay/local_ai_hub"
    package.mkdir(parents=True)
    for root, name in (
        (T13, "app.py"),
        (T13, "http_server.py"),
        (T13, "operational_mode.py"),
        (T08, "async_jobs.py"),
        (T12_STAGE, "services.py"),
    ):
        shutil.copyfile(root / "src/local_ai_hub" / name, package / name)

    script = textwrap.dedent(
        r"""
        import os, sys, threading, time
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        t13 = Path(os.environ["T13_ROOT"])
        t08 = Path(os.environ["T08_ROOT"])
        t12 = Path(os.environ["T12_STAGE"])
        package = Path(os.environ["OVERLAY_PACKAGE"])
        sys.path[:0] = [str(t13 / "src"), str(t12 / "src"), str(t08 / "src")]
        import local_ai_hub
        local_ai_hub.__path__[:] = [
            str(package), str(t12 / "src/local_ai_hub"),
            str(t08 / "src/local_ai_hub"), str(t13 / "src/local_ai_hub"),
        ]
        import local_ai_hub.operational_mode as operational_mode
        from local_ai_hub.app import LocalAIApp
        from local_ai_hub.artifacts import ArtifactStore
        from local_ai_hub.async_jobs import AsyncJobManager
        from local_ai_hub.http_server import Handler
        from local_ai_hub.repo_tools import RepositoryTools
        from local_ai_hub.services import LocalAIServices
        import local_ai_hub.http_server as http_server

        state_dir = Path(os.environ["STATE_DIR"])
        state_dir.mkdir(parents=True, exist_ok=True)
        config = {
            "server": {"state_dir": str(state_dir), "request_timeout_seconds": 5, "bind": "127.0.0.1"},
            "security": {"api_token": ""},
            "async_jobs": {"enabled": True, "result_ttl_seconds": 3600},
            "artifacts": {"ttl_hours": 1},
            "model_conversations": {"max_prompt_tokens": 8192},
            "models": {"general": "local-model", "fast_code": "local-model", "heavy_code": "local-model"},
            "hardware": {"profile": "balanced"},
            "_hardware": {"profile": "balanced", "ram": {"total_gb": 32}, "gpus": []},
            "cache": {"generation": False, "embeddings": False},
            "resilience": {"model_fallback_enabled": False, "serve_stale_on_error": False, "watchdog_enabled": False},
            "token_saving": {"compact_responses": False},
            "ollama": {"enabled": True},
        }

        class Runtime:
            def __init__(self):
                self.request_calls = []
                self.unload_calls = []
            def is_online(self): return True
            def request(self, endpoint, payload=None, **_kwargs):
                self.request_calls.append((endpoint, dict(payload or {})))
                return {"response": "unexpected generation", "done": True}
            def unload_configured_models(self, **kwargs): self.unload_calls.append(dict(kwargs))

        class Scheduler:
            def status(self): return {}
            def submit(self, _model, _tenant, _source, work, **_kwargs): return work()

        class Cache:
            def get(self, _scope, _query): return None, 0.0
            def set(self, _scope, _query, _value): return None

        runtime = Runtime()
        artifacts = ArtifactStore(state_dir, ttl_hours=1)
        service = LocalAIServices(
            config=config, runtime=runtime, scheduler=Scheduler(),
            embeddings=MagicMock(), artifacts=artifacts, telemetry=MagicMock(),
            repo_tools=RepositoryTools(config),
        )
        service.semantic_cache = Cache()
        manager = AsyncJobManager(config, None, artifacts, None)
        app = object.__new__(LocalAIApp)
        app.services, app.async_jobs, app.config, app.runtime = service, manager, config, runtime
        app.preprocessor = app.embeddings = app.reranker = app.debug_traces = None
        app._bind_service_inference_admission()
        manager.executor = app._execute_async_task

        class Recovery:
            @staticmethod
            def fingerprint_payload(_payload): return "joined-test"
            @staticmethod
            def begin(*_args, **_kwargs): return {"claimed": True, "state": "running", "response": None}
            @staticmethod
            def finish(*_args, **_kwargs): return None
        app.recovery = Recovery()
        http_server.APP = app
        http_server._GAMING_DRAIN_TIMEOUT_SECONDS = 0.1
        Handler._begin_trace = lambda self, path: setattr(self, "_trace_request_id", "joined-test")
        Handler._validate_host_and_origin = lambda _self: True
        Handler._tenant_binding_allowed = lambda _self: True
        Handler._validate_payload = lambda _self, _path, _payload: None
        Handler._read_json = lambda self: self._test_payload
        Handler._tenant = lambda _self: "tenant-a"
        Handler._agent = lambda _self: "joined-test"

        original_load = operational_mode.load_operational_mode
        worker_context = threading.local()
        stale_snapshot = threading.Event()
        release_snapshot = threading.Event()
        def interleaved_load(path=None):
            snapshot = original_load(path)
            if getattr(worker_context, "inside_delegate", False) and not stale_snapshot.is_set():
                stale_snapshot.set()
                if not release_snapshot.wait(5): raise TimeoutError("test did not release stale mode snapshot")
            return snapshot
        operational_mode.load_operational_mode = interleaved_load
        original_delegate = service.delegate
        def marked_delegate(*args, **kwargs):
            worker_context.inside_delegate = True
            try: return original_delegate(*args, **kwargs)
            finally: worker_context.inside_delegate = False
        service.delegate = marked_delegate

        operational_mode.set_operational_mode(state_dir, "active")
        def handler(path, payload):
            obj = object.__new__(Handler)
            obj.path, obj.command = path, "POST"
            obj.headers = {"Content-Type": "application/json", "Host": "localhost"}
            obj.client_address, obj.server, obj._test_payload = ("127.0.0.1", 12345), SimpleNamespace(), payload
            responses = []
            obj._send = lambda status, data: responses.append((status, data))
            return obj, responses

        try:
            submitted = manager.submit("tenant-a", "delegate", {"task": "reach the real T12 generation boundary"})
            assert submitted.get("success") is True, submitted
            job_id = submitted["job_id"]
            assert stale_snapshot.wait(8), "T12 _generate did not pause after reading active mode"
            assert manager.inference_actions_active() is True
            assert runtime.request_calls == [], runtime.request_calls

            mode_handler, mode_responses = handler("/api/admin/mode", {"mode": "gaming"})
            Handler.do_POST(mode_handler)
            assert mode_responses and mode_responses[0][0] == 200, mode_responses
            receipt = mode_responses[0][1]
            assert receipt.get("mode_changed") is True, receipt
            assert receipt.get("resources", {}).get("inference_admission_release", {}).get("state") == "timed_out", receipt
            assert runtime.request_calls == [], runtime.request_calls

            release_snapshot.set()
            deadline = time.monotonic() + 8
            final = manager.status("tenant-a", job_id)
            while not final.get("terminal") and time.monotonic() < deadline:
                time.sleep(0.01)
                final = manager.status("tenant-a", job_id)
            assert final.get("terminal") is True, final
            assert final.get("state") in {"cancelled", "failed"}, final
            assert runtime.request_calls == [], runtime.request_calls
            assert manager.inference_actions_active() is False
            assert manager.resource_release_active() is False
        finally:
            release_snapshot.set()
            manager.close()
        """
    )
    env = os.environ.copy()
    env.update(
        {
            "T13_ROOT": str(T13),
            "T08_ROOT": str(T08),
            "T12_STAGE": str(T12_STAGE),
            "OVERLAY_PACKAGE": str(package),
            "STATE_DIR": str(tmp_path / "state"),
            "PYTHONPATH": os.pathsep.join((str(T13 / "src"), str(T12_STAGE / "src"), str(T08 / "src"))),
        }
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=T13,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        print(result.stderr)
    assert result.returncode == 0, (result.stdout, result.stderr)
