from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from local_ai_hub.ollama import OllamaRuntime
from local_ai_hub.scheduler import AffinityScheduler


@pytest.mark.parametrize("available_mb, admitted, resize, preloaded", [(6144, True, False, False), (256, False, False, False), (6144, True, True, False), (6144, True, False, True)])
def test_scheduler_prepares_fallback_before_inference_and_releases_on_unload(tmp_path, available_mb, admitted, resize, preloaded):
    state = {"loaded": resize or preloaded, "context": 512 if resize else 131072, "calls": [], "unprotected": False, "admission_loaded": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            if self.path != "/api/ps":
                self.send_error(404)
                return
            rows = [{"name": "candidate", "context_length": state["context"]}] if state["loaded"] else []
            body = json.dumps({"models": rows}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["calls"].append(payload)
            with socket.socket() as contender:
                try:
                    contender.bind(("127.0.0.1", cuda_port))
                except OSError:
                    pass
                else:
                    state["unprotected"] = True
            if payload.get("keep_alive") == 0:
                state["loaded"] = False
                answer = {"done": True, "done_reason": "unload"}
            else:
                state["loaded"] = True
                state["context"] = payload.get("options", {}).get("num_ctx", state["context"])
                answer = {"done": True, "response": "2" if payload.get("prompt") else ""}
            body = (json.dumps(answer) + "\n").encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    cuda_port = probe.getsockname()[1]
    probe.close()
    config = {
        "server": {"state_dir": str(tmp_path), "ollama_url": f"http://127.0.0.1:{server.server_port}", "request_timeout_seconds": 10},
        "ollama": {"enabled": True, "request_attempts": 1},
        "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                      "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                      "fallback_to_ollama": True, "model_load_timeout_seconds": 10,
                      "models": {"candidate": {"url": f"http://127.0.0.1:{cuda_port}"}}},
        "scheduler": {"model_vram_estimates_bytes": {"candidate": 1024**3}, "max_loaded_models": 1},
    }
    runtime = OllamaRuntime(config)
    def telemetry(force=False):
        if force:
            state["admission_loaded"].append(state["loaded"])
        return {"available": True, "vram_total_mb": 8192, "vram_available_mb": available_mb if force else 6144}

    runtime.vram_balancer = SimpleNamespace(status=telemetry)
    scheduler = None
    try:
        with patch.object(runtime, "ensure_running", return_value=True):
            scheduler = AffinityScheduler(runtime, config)
            result = scheduler.submit("candidate", source="test", wait_timeout=10, execute=lambda: runtime.request(
                "/api/generate", {"model": "candidate", "prompt": "1+1", "stream": False}, timeout=5,
            ))
            if not preloaded:
                assert state["admission_loaded"] and not any(state["admission_loaded"])
            if not admitted:
                assert result["_lah_scheduler_model_switch"]["post_unload_admission"]["state"] == "rejected"
                assert state["calls"] == []
                assert runtime._mixed_fallback_guard is not None
                assert not runtime._mixed_fallback_admitted
                return
            assert result["response"] == "2"
            assert result["_lah_provider"] == "ollama"
            if not preloaded:
                assert result["_lah_scheduler_model_switch"]["post_unload_admission"]["state"] == "admitted"
            assert [item.get("prompt") for item in state["calls"]] == (["1+1"] if preloaded else ["", "", "1+1"] if resize else ["", "1+1"])
            assert not state["unprotected"]
            # A different local client can unload a runner behind the scheduler.
            # The detection happens before inference, so the next job can safely
            # prepare it again without replaying the failed request.
            state["loaded"] = False
            calls_before = len(state["calls"])
            rejected = scheduler.submit("candidate", source="test", wait_timeout=10, execute=lambda: runtime.request(
                "/api/generate", {"model": "candidate", "prompt": "must not run", "stream": False}, timeout=5,
            ))
            assert rejected["operation_not_started"] is True
            assert rejected["error_code"] == "model_preparation_required"
            assert len(state["calls"]) == calls_before
            recovered = scheduler.submit("candidate", source="test", wait_timeout=10, execute=lambda: runtime.request(
                "/api/generate", {"model": "candidate", "prompt": "1+1", "stream": False}, timeout=5,
            ))
            assert recovered["response"] == "2"
            scheduler.submit("candidate", source="test", wait_timeout=10, execute=lambda: {
                "success": False, "error": "ambiguous", "operation_not_started": True,
                "error_code": "model_preparation_required", "outcome_unknown": True,
            })
            assert scheduler._internal_gpu_uncertain
            with socket.socket() as other:
                try:
                    other.bind(("127.0.0.1", cuda_port))
                except OSError:
                    pass
                else:
                    raise AssertionError("CUDA port was not reserved")
            assert runtime.unload_model("candidate")
            with socket.socket() as other:
                other.bind(("127.0.0.1", cuda_port))
    finally:
        if scheduler is not None:
            scheduler.close()
        runtime._release_mixed_fallback_guard("candidate")
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("available_mb, outcome", [(6144, "success"), (256, "reject"), (6144, "partial")])
def test_scheduler_routes_cuda_only_after_ollama_unload_and_admission(tmp_path, available_mb, outcome):
    state = {"ollama_loaded": True, "cuda_loaded": False, "events": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, body, content_type="application/json"):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.server.kind == "ollama" and self.path == "/api/ps":
                models = [{"name": "other", "context_length": 4096}] if state["ollama_loaded"] else []
                self.respond(json.dumps({"models": models}).encode())
            elif self.server.kind == "cuda" and self.path == "/health":
                self.respond(b'{}')
            elif self.server.kind == "cuda" and self.path == "/models":
                status = "loaded" if state["cuda_loaded"] else "unloaded"
                self.respond(json.dumps({"data": [{"id": "alias", "status": {"value": status}}]}).encode())
            else:
                self.send_error(404)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.server.kind == "ollama" and self.path == "/api/generate" and payload.get("keep_alive") == 0:
                state["events"].append("unload_ollama")
                state["ollama_loaded"] = False
                self.respond(b'{"done":true,"done_reason":"unload"}\n')
            elif self.server.kind == "cuda" and self.path == "/models/load":
                state["events"].append("load_cuda")
                state["cuda_loaded"] = True
                self.respond(b'{"success":true}')
            elif self.server.kind == "cuda" and self.path == "/v1/chat/completions":
                state["events"].append("generate_cuda")
                state["generation_payload"] = payload
                events = [
                    {"choices": [{"index": 0, "delta": {"content": "2"}, "finish_reason": None}]},
                    {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                ]
                if outcome == "partial":
                    body = "data: " + json.dumps(events[0]) + "\n\n"
                else:
                    body = "".join("data: " + json.dumps(event) + "\n\n" for event in events) + "data: [DONE]\n\n"
                self.respond(body.encode(), "text/event-stream")
            else:
                self.send_error(404)

    ollama = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    cuda = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    ollama.kind, cuda.kind = "ollama", "cuda"
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (ollama, cuda)]
    for thread in threads:
        thread.start()
    config = {
        "server": {"state_dir": str(tmp_path), "ollama_url": f"http://127.0.0.1:{ollama.server_port}", "request_timeout_seconds": 10},
        "ollama": {"enabled": True, "request_attempts": 1},
        "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                      "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate", "fallback_to_ollama": True,
                      "model_load_timeout_seconds": 10,
                      "models": {"candidate": {"url": f"http://127.0.0.1:{cuda.server_port}", "served_model": "alias"}}},
        "scheduler": {"model_vram_estimates_bytes": {"candidate": 1024**3}, "max_loaded_models": 1},
    }
    runtime = OllamaRuntime(config)
    def telemetry(force=False):
        if force:
            state["events"].append("admit_while_loaded" if state["ollama_loaded"] else "admit")
        return {"available": True, "vram_total_mb": 8192, "vram_available_mb": available_mb if force else 6144}
    runtime.vram_balancer = SimpleNamespace(status=telemetry)
    scheduler = None
    try:
        with patch.object(runtime.llama_cpp_managed, "status", return_value={"online": True, "mode": "CUDA0"}):
            scheduler = AffinityScheduler(runtime, config)
            result = scheduler.submit("candidate", source="test", wait_timeout=10, execute=lambda: runtime.request(
                "/api/generate", {"model": "candidate", "prompt": "1+1", "stream": False, "think": False}, timeout=5,
            ))
        if outcome == "success":
            assert result["response"] == "2"
            assert result["_lah_provider"] == "llama.cpp-cuda"
            assert state["generation_payload"]["reasoning_effort"] == "none"
            assert state["events"] == ["unload_ollama", "admit", "load_cuda", "generate_cuda"]
        elif outcome == "reject":
            assert result["_lah_scheduler_model_switch"]["post_unload_admission"]["state"] == "rejected"
            assert state["events"] == ["unload_ollama", "admit"]
        else:
            assert result["_lah_partial_response"] is True
            assert scheduler._internal_gpu_uncertain
            assert state["events"] == ["unload_ollama", "admit", "load_cuda", "generate_cuda"]
    finally:
        if scheduler is not None:
            scheduler.close()
        for server in (ollama, cuda):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=5)
