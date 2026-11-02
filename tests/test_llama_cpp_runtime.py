from __future__ import annotations

import hashlib
import io
import socket
import threading
import time
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.llama_cpp_runtime import LlamaCppManagedRuntime, llama_cpp_backend_selection, llama_cpp_managed_selected


class LlamaCppRuntimeTests(unittest.TestCase):
    def _prepared_fallback(self, runtime):
        guard = runtime._reserve_mixed_cuda_endpoint()
        self.assertIsNotNone(guard)
        runtime._mixed_fallback_guard = guard
        runtime._mixed_fallback_model = "candidate"
        runtime._mixed_fallback_admitted = True
        self.addCleanup(runtime._release_mixed_fallback_guard, "candidate")

    def test_mixed_route_uses_cuda_only_for_explicit_model(self):
        from local_ai_hub.ollama import OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True, "request_attempts": 1},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "fallback_to_ollama": True, "models": {"candidate": {"url": "http://127.0.0.1:12438"}}},
            })
            calls = []
            def llama_request(endpoint, payload, callback, **kwargs):
                calls.append(payload["model"])
                return {"message": {"content": "CUDA"}, "done": True}
            runtime.llama_cpp = SimpleNamespace(request_stream=llama_request)
            ready = {"complete": True, "models": [{"name": "candidate", "backend": "llama.cpp-cuda", "endpoint_url": "http://127.0.0.1:12438", "status": "loaded"}]}
            with (patch.object(runtime, "loaded_model_inventory", return_value=ready),
                  patch.object(runtime.llama_cpp_managed, "status", return_value={"mode": "CUDA0"})):
                result = runtime.request_stream("/api/chat", {"model": "candidate", "messages": []}, None, timeout=10)
            self.assertEqual(result["message"]["content"], "CUDA")
            self.assertEqual(result["_lah_provider"], "llama.cpp-cuda")
            self.assertEqual(calls, ["candidate"])

    def test_mixed_runtime_wires_managed_owner_to_router(self):
        from local_ai_hub.ollama import OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "models": {"candidate": {"url": "http://127.0.0.1:12438"},
                                         "other": {"url": "http://127.0.0.1:12438"}}},
            })
            self.assertIs(runtime.llama_cpp.managed_runtime, runtime.llama_cpp_managed)
            self.assertTrue(runtime.llama_cpp.supports_model("candidate"))
            self.assertFalse(runtime.llama_cpp.supports_model("other"))
            self.assertIsNone(runtime.llama_cpp._entry("other"))
            self.assertTrue(runtime.supports_post_unload_admission("candidate"))
            with patch.object(runtime.llama_cpp_managed, "is_online", return_value=True):
                status = runtime.llama_cpp_managed.status()
            self.assertTrue(status["selected"])
            self.assertTrue(status["online"])
            runtime.config["llama_cpp"]["fallback_to_ollama"] = False
            with patch.object(runtime, "is_online", return_value=True):
                self.assertTrue(runtime.ensure_running())

    def test_mixed_inventory_reports_only_selected_logical_model(self):
        from local_ai_hub.llama_cpp import LlamaCppRouter

        router = LlamaCppRouter({"llama_cpp": {"mode": "on", "managed_with_ollama": True,
            "managed_model_logical": "candidate", "models": {
                "candidate": {"url": "http://127.0.0.1:12438", "served_model": "fp4-alias"},
                "other": {"url": "http://127.0.0.1:12438", "served_model": "other-alias"},
            }}}, managed_runtime=SimpleNamespace(status=lambda: {"mode": "CUDA0"}))
        with patch.object(router, "_model_info", return_value={"fp4-alias": {"status": {"value": "loaded"}}}):
            snapshot = router.loaded_model_inventory()
        self.assertTrue(snapshot["complete"])
        self.assertEqual(snapshot["models"][0]["name"], "candidate")
        self.assertEqual(snapshot["models"][0]["backend"], "llama.cpp-cuda")
        self.assertEqual(snapshot["models"][0]["served_model"], "fp4-alias")
        self.assertNotIn("other", snapshot["endpoint_status"])

    def test_mixed_fallback_never_replays_partial_cuda_output(self):
        from local_ai_hub.ollama import OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True, "request_attempts": 1},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "fallback_to_ollama": True, "models": {"candidate": {"url": "http://127.0.0.1:12438"}}},
            })
            def partial(_endpoint, _payload, callback, **kwargs):
                callback("partial")
                return {"_lah_backend_unavailable": "interrupted", "error": "interrupted"}
            runtime.llama_cpp = SimpleNamespace(request_stream=partial)
            ready = {"complete": True, "models": [{"name": "candidate", "backend": "llama.cpp-cuda", "endpoint_url": "http://127.0.0.1:12438", "status": "loaded"}]}
            with (patch.object(runtime, "loaded_model_inventory", return_value=ready),
                  patch("local_ai_hub.ollama.urlopen") as opener):
                result = runtime.request_stream("/api/chat", {"model": "candidate", "messages": []}, lambda _: None, timeout=10)
            opener.assert_not_called()
            self.assertTrue(result.get("_lah_partial_response"))
            self.assertIn("error", result)

    def test_mixed_fallback_uses_ollama_only_when_explicitly_enabled(self):
        from local_ai_hub.ollama import OllamaRuntime

        for fallback, expected in ((True, "ollama"), (False, "error")):
            with self.subTest(fallback=fallback), tempfile.TemporaryDirectory() as temp:
                runtime = OllamaRuntime({
                    "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                    "ollama": {"enabled": True, "request_attempts": 1},
                    "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                                  "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                                  "fallback_to_ollama": fallback, "models": {"candidate": {"url": "http://127.0.0.1:12438"}}},
                })
                runtime.llama_cpp = SimpleNamespace(request_stream=lambda *args, **kwargs: None)
                if fallback:
                    self._prepared_fallback(runtime)
                with (patch.object(runtime, "loaded_model_inventory", return_value={"complete": True, "models": [{"name": "candidate", "backend": "ollama", "context_length": 131072}]}),
                      patch("local_ai_hub.ollama.socket.create_connection", side_effect=ConnectionRefusedError),
                      patch("local_ai_hub.ollama.urlopen", return_value=io.BytesIO(b'{"message":{"content":"ok"},"done":true}\n')) as opener):
                    result = runtime.request_stream("/api/chat", {"model": "candidate", "messages": []}, None, timeout=10)
                self.addCleanup(runtime._release_mixed_fallback_guard, "candidate")
                if expected == "ollama":
                    self.assertEqual(result["message"]["content"], "ok")
                    self.assertEqual(result["_lah_provider"], "ollama")
                    self.assertTrue(opener.called)
                else:
                    self.assertIn("error", result)
                    opener.assert_not_called()

    def test_mixed_route_does_not_replay_cancelled_or_unknown_outcomes(self):
        from local_ai_hub.ollama import OllamaRuntime

        for flag in ("timed_out", "preempted", "cancelled", "outcome_unknown"):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as temp:
                runtime = OllamaRuntime({
                    "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                    "ollama": {"enabled": True},
                    "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                                  "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                                  "fallback_to_ollama": True, "models": {"candidate": {"url": "http://127.0.0.1:12438"}}},
                })
                runtime.llama_cpp = SimpleNamespace(request_stream=lambda *args, **kwargs: {"_lah_backend_unavailable": "failed", flag: True})
                ready = {"complete": True, "models": [{"name": "candidate", "backend": "llama.cpp-cuda", "endpoint_url": "http://127.0.0.1:12438", "status": "loaded"}]}
                with (patch.object(runtime, "loaded_model_inventory", return_value=ready),
                      patch("local_ai_hub.ollama.urlopen") as opener):
                    result = runtime.request_stream("/api/chat", {"model": "candidate", "messages": []}, None, timeout=10)
                self.assertTrue(result.get(flag))
                opener.assert_not_called()

    def test_mixed_fallback_does_not_load_ollama_while_cuda_process_is_alive(self):
        from local_ai_hub.ollama import OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True, "request_attempts": 1},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "fallback_to_ollama": True, "models": {"candidate": {"url": "http://127.0.0.1:12438"}}},
            })
            runtime.llama_cpp = SimpleNamespace(request_stream=lambda *args, **kwargs: {"_lah_backend_unavailable": "unhealthy"})
            with (patch.object(runtime.llama_cpp_managed, "_managed_pid_alive", return_value=True),
                  patch("local_ai_hub.ollama.urlopen") as opener):
                result = runtime.request_stream("/api/chat", {"model": "candidate", "messages": []}, None, timeout=10)
            opener.assert_not_called()
            self.assertIn("error", result)

    def test_mixed_fallback_holds_cuda_port_until_ollama_unload_confirmed(self):
        from local_ai_hub.ollama import OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            probe = socket.socket()
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
            probe.close()
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True, "request_attempts": 1},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "fallback_to_ollama": True, "models": {"candidate": {"url": f"http://127.0.0.1:{port}"}}},
            })
            runtime.llama_cpp = SimpleNamespace(request_stream=lambda *args, **kwargs: {"_lah_backend_unavailable": "offline"})
            self._prepared_fallback(runtime)
            def ollama_response(*_args, **_kwargs):
                other = socket.socket()
                try:
                    with self.assertRaises(OSError):
                        other.bind(("127.0.0.1", port))
                finally:
                    other.close()
                return io.BytesIO(b'{"message":{"content":"fallback"},"done":true}\n')
            with (patch.object(runtime, "loaded_model_inventory", return_value={"complete": True, "models": [{"name": "candidate", "backend": "ollama", "context_length": 131072}]}),
                  patch("local_ai_hub.ollama.urlopen", side_effect=ollama_response)):
                result = runtime.request_stream("/api/chat", {"model": "candidate", "messages": []}, None, timeout=10)
            self.assertEqual(result["message"]["content"], "fallback")
            after = socket.socket()
            try:
                with self.assertRaises(OSError):
                    after.bind(("127.0.0.1", port))
                with (patch.object(runtime, "_request_stream_tracked", return_value={"done_reason": "unload"}),
                      patch.object(runtime, "loaded_model_inventory", return_value={"complete": True, "models": []})):
                    self.assertTrue(runtime.unload_inventory_model({"name": "candidate", "backend": "ollama"}))
                after.bind(("127.0.0.1", port))
            finally:
                after.close()

    def test_mixed_generation_refuses_cuda_when_ollama_model_is_also_resident(self):
        from local_ai_hub.ollama import OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "fallback_to_ollama": True, "models": {"candidate": {"url": "http://127.0.0.1:12438"}}},
            })
            runtime.llama_cpp = SimpleNamespace(request_stream=lambda *args, **kwargs: {"done": True})
            inventory = {"complete": True, "models": [{"name": "candidate", "backend": "ollama"},
                         {"name": "candidate", "backend": "llama.cpp-cuda", "endpoint_url": "http://127.0.0.1:12438"}]}
            with patch.object(runtime, "loaded_model_inventory", return_value=inventory):
                result = runtime.request_stream("/api/chat", {"model": "candidate", "messages": []}, None, timeout=10)
            self.assertIn("error", result)

    def test_mixed_fallback_timeout_retains_residency_guard(self):
        from local_ai_hub.ollama import OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            probe = socket.socket()
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
            probe.close()
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True, "request_attempts": 1},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate", "fallback_to_ollama": True,
                              "models": {"candidate": {"url": f"http://127.0.0.1:{port}"}}},
            })
            runtime.llama_cpp = SimpleNamespace(request_stream=lambda *args, **kwargs: None)
            self._prepared_fallback(runtime)
            self.addCleanup(runtime._release_mixed_fallback_guard, "candidate")
            with (patch.object(runtime, "loaded_model_inventory", return_value={"complete": True, "models": [{"name": "candidate", "backend": "ollama", "context_length": 131072}]}),
                  patch("local_ai_hub.ollama.urlopen", side_effect=TimeoutError("unknown outcome")) as request):
                result = runtime.request_stream("/api/chat", {"model": "candidate", "messages": []}, None, timeout=10)
            self.assertIn("error", result)
            request.assert_called_once()
            self.assertIsNotNone(runtime._mixed_fallback_guard, result)
            with socket.socket() as other:
                with self.assertRaises(OSError):
                    other.bind(("127.0.0.1", port))

    def test_mixed_fallback_does_not_infer_without_admitted_preparation(self):
        from local_ai_hub.ollama import OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "fallback_to_ollama": True,
                              "models": {"candidate": {"url": "http://127.0.0.1:12438"}}},
            })
            with (patch.object(runtime, "loaded_model_inventory", return_value={"complete": True, "models": []}),
                  patch("local_ai_hub.ollama.urlopen") as request):
                result = runtime.request_stream("/api/chat", {"model": "candidate", "messages": []}, None, timeout=10)
            self.assertIn("error", result)
            request.assert_not_called()

    def test_mixed_fallback_rejects_unloaded_previously_admitted_model(self):
        from local_ai_hub.ollama import OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "fallback_to_ollama": True,
                              "models": {"candidate": {"url": "http://127.0.0.1:12438"}}},
            })
            self._prepared_fallback(runtime)
            with (patch.object(runtime, "loaded_model_inventory", return_value={"complete": True, "models": []}),
                  patch("local_ai_hub.ollama.urlopen") as request):
                result = runtime.request_stream("/api/chat", {"model": "candidate", "messages": []}, None, timeout=10)
            self.assertIn("error", result)
            request.assert_not_called()

    def test_mixed_fallback_rejects_resident_model_with_insufficient_context(self):
        from local_ai_hub.ollama import OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "fallback_to_ollama": True,
                              "models": {"candidate": {"url": "http://127.0.0.1:12438"}}},
            })
            self._prepared_fallback(runtime)
            snapshot = {"complete": True, "models": [{"name": "candidate", "backend": "ollama", "context_length": 128}]}
            with (patch.object(runtime, "loaded_model_inventory", return_value=snapshot),
                  patch("local_ai_hub.ollama.urlopen") as request):
                result = runtime.request_stream("/api/chat", {"model": "candidate", "messages": []}, None, timeout=1)
            self.assertIn("error", result)
            request.assert_not_called()

    def test_mixed_preparation_requires_vram_admission(self):
        from local_ai_hub.ollama import ModelPreparationAdmissionRejected, OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "fallback_to_ollama": True,
                              "models": {"candidate": {"url": "http://127.0.0.1:12438"}}},
            })
            with (patch.object(runtime, "loaded_model_inventory") as inventory,
                  patch.object(runtime.llama_cpp, "ensure_model") as load):
                with self.assertRaises(ModelPreparationAdmissionRejected):
                    runtime.prepare_model("candidate")
            inventory.assert_not_called()
            load.assert_not_called()

    def test_mixed_cuda_rejects_context_smaller_than_execution_profile(self):
        from local_ai_hub.ollama import ModelPreparationAdmissionRejected, OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "models": {"candidate": {"url": "http://127.0.0.1:12438", "context_length": 512}}},
            })
            with (patch.object(runtime, "loaded_model_inventory", return_value={"complete": True, "models": []}),
                  patch.object(runtime.llama_cpp, "ensure_model", return_value=True) as load):
                with self.assertRaises(ModelPreparationAdmissionRejected) as rejected:
                    runtime.prepare_model("candidate", post_unload_admission=lambda: {"state": "admitted"})
            self.assertEqual(rejected.exception.admission["reason"], "mixed_cuda_context_insufficient")
            load.assert_not_called()

    def test_legacy_load_rejects_mixed_model_without_scheduler_admission(self):
        from local_ai_hub.ollama import OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "models": {"candidate": {"url": "http://127.0.0.1:12438"}}},
            })
            with patch.object(runtime.llama_cpp, "ensure_model", return_value=True) as load:
                self.assertFalse(runtime.load_model("candidate"))
            load.assert_not_called()

    def test_uncertain_fallback_preparation_keeps_cuda_guard(self):
        from local_ai_hub.ollama import OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "fallback_to_ollama": True,
                              "models": {"candidate": {"url": "http://127.0.0.1:12438"}}},
            })
            guard = SimpleNamespace(closed=False)
            guard.close = lambda: setattr(guard, "closed", True)
            self.addCleanup(runtime._release_mixed_fallback_guard, "candidate")
            with (patch.object(runtime, "loaded_model_inventory", return_value={"complete": False}),
                  patch.object(runtime, "_reserve_mixed_cuda_endpoint", return_value=guard),
                  patch.object(runtime, "_prepare_ollama_fallback", side_effect=TimeoutError("unknown outcome"))):
                with self.assertRaises(TimeoutError):
                    runtime.prepare_model("candidate", post_unload_admission=lambda: {"state": "admitted"})
            self.assertFalse(guard.closed)
            self.assertIs(runtime._mixed_fallback_guard, guard)
            with (patch.object(runtime, "loaded_model_inventory", return_value={"complete": True, "models": []}),
                  patch("local_ai_hub.ollama.urlopen") as request):
                result = runtime.request_stream("/api/chat", {"model": "candidate", "messages": []}, None, timeout=10)
            self.assertIn("error", result)
            request.assert_not_called()

    def test_fallback_resize_keeps_guard_during_confirmed_unload(self):
        from local_ai_hub.ollama import OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "fallback_to_ollama": True,
                              "models": {"candidate": {"url": "http://127.0.0.1:12438"}}},
            })
            guard = SimpleNamespace(closed=False)
            guard.close = lambda: setattr(guard, "closed", True)
            self.addCleanup(runtime._release_mixed_fallback_guard, "candidate")
            def prepare(*_args, **_kwargs):
                with patch.object(runtime, "loaded_model_inventory", return_value={"complete": True, "models": []}):
                    self.assertTrue(runtime._confirm_mixed_fallback_unloaded("candidate", should_stop=None, deadline=None))
                self.assertFalse(guard.closed)
                return []
            with (patch.object(runtime, "loaded_model_inventory", return_value={"complete": False}),
                  patch.object(runtime, "_reserve_mixed_cuda_endpoint", return_value=guard),
                  patch.object(runtime, "_prepare_ollama_fallback", side_effect=prepare)):
                self.assertEqual(runtime.prepare_model("candidate", post_unload_admission=lambda: {"state": "admitted"}), [])

    def test_mixed_preparation_lock_respects_deadline(self):
        from local_ai_hub.ollama import OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "models": {"candidate": {"url": "http://127.0.0.1:12438"}}},
            })
            results = []
            def prepare():
                try:
                    runtime.prepare_model("candidate", deadline=time.monotonic() + 0.1)
                except Exception as exc:
                    results.append(type(exc))
            with runtime._mixed_provider_lock:
                thread = threading.Thread(target=prepare)
                thread.start()
                thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(results, [TimeoutError])

    def test_mixed_fallback_can_reuse_ollama_when_cuda_is_stopped(self):
        from local_ai_hub.ollama import OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True, "request_attempts": 1},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "fallback_to_ollama": True, "models": {"candidate": {"url": "http://127.0.0.1:12438"}}},
            })
            runtime.llama_cpp = SimpleNamespace(request_stream=lambda *args, **kwargs: {"done": True})
            inventory = {"complete": True, "models": [{"name": "candidate", "backend": "ollama", "context_length": 131072}]}
            self._prepared_fallback(runtime)
            with (patch.object(runtime, "loaded_model_inventory", return_value=inventory),
                  patch("local_ai_hub.ollama.urlopen", return_value=io.BytesIO(b'{"message":{"content":"fallback"},"done":true}\n'))):
                result = runtime.request_stream("/api/chat", {"model": "candidate", "messages": []}, None, timeout=10)
            self.assertEqual(result["message"]["content"], "fallback")
            runtime._release_mixed_fallback_guard("candidate")

    def test_mixed_inventory_unloads_ollama_row_on_ollama_backend(self):
        from local_ai_hub.ollama import OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True, "request_attempts": 1},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "fallback_to_ollama": True, "models": {"candidate": {"url": "http://127.0.0.1:12438"}}},
            })
            runtime.llama_cpp = SimpleNamespace(request_stream=lambda *args, **kwargs: {"error": "wrong backend"})
            with patch("local_ai_hub.ollama.urlopen", return_value=io.BytesIO(b'{"done":true,"done_reason":"unload"}\n')) as opener:
                self.assertTrue(runtime.unload_inventory_model({"name": "candidate", "backend": "ollama"}))
            self.assertTrue(opener.called)
            runtime.config["ollama"]["enabled"] = False
            with patch("local_ai_hub.ollama.urlopen") as opener:
                self.assertFalse(runtime.unload_inventory_model({"name": "candidate", "backend": "ollama"}))
            opener.assert_not_called()

    def test_fallback_guard_stays_held_until_unload_is_verified(self):
        from local_ai_hub.ollama import OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "models": {"candidate": {"url": "http://127.0.0.1:12438"}}},
            })
            guard = SimpleNamespace(closed=False)
            guard.close = lambda: setattr(guard, "closed", True)
            runtime._mixed_fallback_guard, runtime._mixed_fallback_model = guard, "candidate"
            with (patch.object(runtime, "_request_stream_tracked", return_value={"done_reason": "unload"}),
                  patch.object(runtime, "loaded_model_inventory", return_value={"complete": True, "models": [{"name": "candidate", "backend": "ollama"}]})):
                self.assertFalse(runtime.unload_inventory_model({"name": "candidate", "backend": "ollama"}))
            self.assertFalse(guard.closed)
            runtime._release_mixed_fallback_guard("candidate")

    def test_mixed_inventory_unloads_configured_cuda_alias_by_its_logical_name(self):
        from local_ai_hub.ollama import OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "models": {"candidate": {"url": "http://127.0.0.1:12438", "served_model": "fp4-alias"}}},
            })
            row = {"name": "candidate", "served_model": "fp4-alias", "backend": "llama.cpp-cuda", "endpoint_url": "http://127.0.0.1:12438"}
            with patch.object(runtime.llama_cpp, "unload_model", return_value=True) as unload:
                self.assertTrue(runtime.unload_inventory_model(row))
            self.assertEqual(unload.call_args.args[0], "fp4-alias")
            with patch.object(runtime.llama_cpp, "unload_model", return_value=True) as unload:
                self.assertFalse(runtime.unload_inventory_model({**row, "endpoint_url": "http://127.0.0.1:12439"}))
            unload.assert_not_called()

    def test_mixed_preparation_unloads_other_backend_then_checks_admission(self):
        from local_ai_hub.ollama import OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "models": {"candidate": {"url": "http://127.0.0.1:12438", "served_model": "fp4", "context_length": 131072}}},
            })
            events = []
            row = {"name": "candidate", "backend": "ollama", "endpoint_id": "http://127.0.0.1:11434"}
            selected_row = {"name": "candidate", "backend": "llama.cpp-cuda", "endpoint_url": "http://127.0.0.1:12438", "status": "loaded"}
            snapshots = [{"complete": True, "models": [row]}, {"complete": True, "models": []}, {"complete": True, "models": [selected_row]}]
            with (patch.object(runtime, "loaded_model_inventory", side_effect=snapshots),
                  patch.object(runtime, "unload_inventory_model", side_effect=lambda *_a, **_kw: events.append("unload") or True),
                  patch.object(runtime.llama_cpp, "ensure_model", side_effect=lambda *_a, **_kw: events.append("load") or True)):
                evicted = runtime.prepare_model("candidate", post_unload_admission=lambda: events.append("admit") or {"state": "admitted"})
            self.assertEqual(events, ["unload", "admit", "load"])
            self.assertEqual(evicted, ["candidate"])

    def test_mixed_preparation_rejects_cpu_fallback_for_cuda_route(self):
        from local_ai_hub.ollama import ModelPreparationAdmissionRejected, OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "models": {"candidate": {"url": "http://127.0.0.1:12438"}}},
            })
            snapshots = [{"complete": True, "models": []}, {"complete": True, "models": [
                {"name": "candidate", "backend": "llama.cpp-cpu", "endpoint_url": "http://127.0.0.1:12438", "status": "loaded"}]}]
            with (patch.object(runtime, "loaded_model_inventory", side_effect=snapshots),
                  patch.object(runtime.llama_cpp, "ensure_model", return_value=True)):
                with self.assertRaises(ModelPreparationAdmissionRejected):
                    runtime.prepare_model("candidate")

    def test_mixed_preparation_does_not_load_when_managed_server_is_cpu_only(self):
        from local_ai_hub.ollama import ModelPreparationAdmissionRejected, OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "models": {"candidate": {"url": "http://127.0.0.1:12438"}}},
            })
            with (patch.object(runtime.llama_cpp_managed, "status", return_value={"online": True, "mode": "none"}),
                  patch.object(runtime, "loaded_model_inventory", return_value={"complete": True, "models": []}),
                  patch.object(runtime.llama_cpp, "ensure_model", return_value=True) as load):
                with self.assertRaises(ModelPreparationAdmissionRejected):
                    runtime.prepare_model("candidate")
            load.assert_not_called()

    def test_mixed_preparation_never_loads_when_unload_is_unconfirmed(self):
        from local_ai_hub.ollama import ModelPreparationAdmissionRejected, OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "models": {"candidate": {"url": "http://127.0.0.1:12438", "served_model": "fp4"}}},
            })
            row = {"name": "other", "backend": "ollama", "endpoint_id": "http://127.0.0.1:11434"}
            snapshot = {"complete": True, "models": [row]}
            with (patch.object(runtime, "loaded_model_inventory", return_value=snapshot),
                  patch.object(runtime, "unload_inventory_model", return_value=True),
                  patch.object(runtime.llama_cpp, "ensure_model") as load):
                with self.assertRaises(ModelPreparationAdmissionRejected):
                    runtime.prepare_model("candidate", post_unload_admission=lambda: {"state": "admitted"})
            load.assert_not_called()

    def test_mixed_preparation_rejects_unadmitted_loading_model(self):
        from local_ai_hub.ollama import ModelPreparationAdmissionRejected, OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "models": {"candidate": {"url": "http://127.0.0.1:12438"}}},
            })
            row = {"name": "candidate", "backend": "llama.cpp-cuda", "endpoint_url": "http://127.0.0.1:12438", "status": "loading"}
            with (patch.object(runtime, "loaded_model_inventory", return_value={"complete": True, "models": [row]}),
                  patch.object(runtime.llama_cpp, "ensure_model", return_value=True) as load):
                with self.assertRaises(ModelPreparationAdmissionRejected):
                    runtime.prepare_model("candidate", post_unload_admission=lambda: {"state": "admitted"})
            load.assert_not_called()

    def test_mixed_preparation_falls_back_only_with_reserved_cuda_endpoint(self):
        from local_ai_hub.ollama import OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "fallback_to_ollama": True,
                              "models": {"candidate": {"url": "http://127.0.0.1:12438"}}},
            })
            guard = SimpleNamespace(closed=False)
            guard.close = lambda: setattr(guard, "closed", True)
            with (patch.object(runtime, "loaded_model_inventory", return_value={"complete": False}),
                  patch.object(runtime, "_reserve_mixed_cuda_endpoint", return_value=guard),
                  patch.object(runtime, "_prepare_ollama_fallback", return_value=["other"]) as fallback):
                self.assertEqual(runtime.prepare_model("candidate", post_unload_admission=lambda: {"state": "admitted"}), ["other"])
            self.assertTrue(fallback.called)
            self.assertFalse(guard.closed)
            runtime._release_mixed_fallback_guard("candidate")
            self.assertTrue(guard.closed)

    def test_mixed_fallback_preparation_unloads_conflicts_and_checks_admission(self):
        from local_ai_hub.ollama import OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True}, "models": {"fast_code": "candidate"},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "fallback_to_ollama": True, "models": {"candidate": {"url": "http://127.0.0.1:12438"}}},
            })
            guard = SimpleNamespace(close=lambda: None)
            events = []
            other = {"name": "other", "backend": "ollama", "context_length": 4096}
            snapshots = [{"complete": False}, {"complete": True, "models": [other]}, {"complete": True, "models": []}]
            with (patch.object(runtime, "loaded_model_inventory", side_effect=snapshots),
                  patch.object(runtime, "_reserve_mixed_cuda_endpoint", return_value=guard),
                  patch.object(runtime, "ensure_running", return_value=True),
                  patch.object(runtime, "unload_inventory_model", side_effect=lambda *_a, **_kw: events.append("unload") or True),
                  patch.object(runtime, "_request_stream_tracked", side_effect=lambda *_a, **kw: events.append("load" if kw.get("force_ollama") else "wrong") or {"done": True})):
                result = runtime.prepare_model("candidate", post_unload_admission=lambda: events.append("admit") or {"state": "admitted"})
            self.assertEqual(events, ["unload", "admit", "load"])
            self.assertEqual(result, ["other"])

    def test_mixed_failed_cuda_load_can_fall_back_after_owner_is_gone(self):
        from local_ai_hub.ollama import OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": True},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "fallback_to_ollama": True, "models": {"candidate": {"url": "http://127.0.0.1:12438", "context_length": 131072}}},
            })
            guard = SimpleNamespace(close=lambda: None)
            with (patch.object(runtime, "loaded_model_inventory", return_value={"complete": True, "models": []}),
                  patch.object(runtime.llama_cpp, "ensure_model", return_value=False),
                  patch.object(runtime, "_reserve_mixed_cuda_endpoint", return_value=guard),
                  patch.object(runtime, "_prepare_ollama_fallback", return_value=[]) as fallback):
                self.assertEqual(runtime.prepare_model("candidate", post_unload_admission=lambda: {"state": "admitted"}), [])
            self.assertTrue(fallback.called)
            runtime._release_mixed_fallback_guard("candidate")

    def test_custom_model_selects_only_explicit_route_among_merged_defaults(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = LlamaCppManagedRuntime({
                "server": {"state_dir": temp},
                "models": {"fast_code": "default"},
                "llama_cpp": {"managed_model_sha256": "a" * 64, "managed_model_logical": "candidate", "models": {
                    "default": {"url": "http://127.0.0.1:12438", "served_model": "default-alias"},
                    "candidate": {"url": "http://127.0.0.1:12439", "served_model": "candidate-alias"},
                }},
            })
            self.assertEqual(runtime._configured_routes(), (12439, [("candidate-alias", "candidate")]))
            self.assertEqual(runtime._default_alias(), "candidate-alias")
            runtime._write_preset()
            preset = (runtime.runtime_dir / "hub.models.ini").read_text(encoding="utf-8")
            self.assertIn("[candidate-alias]", preset)
            self.assertIn("load-on-startup = true", preset)
            self.assertNotIn("[default-alias]", preset)

    def test_mixed_managed_server_starts_without_loading_gpu_model(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = LlamaCppManagedRuntime({
                "server": {"state_dir": temp},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "models": {"candidate": {"url": "http://127.0.0.1:12438", "served_model": "fp4"}}},
            })
            runtime._write_preset(device="CUDA0")
            preset = (runtime.runtime_dir / "hub.models.ini").read_text(encoding="utf-8")
            self.assertIn("[fp4]", preset)
            self.assertIn("load-on-startup = false", preset)
            self.assertNotIn("load-on-startup = true", preset)
            self.assertEqual([device for device, _timeout in runtime._device_attempts(False)], ["CUDA0"])

    def test_mixed_readiness_accepts_unloaded_configured_model(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = LlamaCppManagedRuntime({
                "server": {"state_dir": temp},
                "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                              "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                              "models": {"candidate": {"url": "http://127.0.0.1:12438", "served_model": "fp4"}}},
            })
            data = b'{"data":[{"id":"fp4","status":{"value":"unloaded"}}]}'
            with patch("local_ai_hub.llama_cpp_runtime.urlopen", side_effect=lambda *args, **kwargs: io.BytesIO(data)):
                self.assertTrue(runtime._ready("http://127.0.0.1:12438", 1, SimpleNamespace(poll=lambda: None)))

    def test_managed_start_does_not_spawn_after_cancellation_during_provision(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = LlamaCppManagedRuntime({"server": {"state_dir": temp}, "llama_cpp": {"mode": "on"}})
            cancelled = [False]
            def provision():
                cancelled[0] = True
                return runtime.runtime_dir / "llama-server.exe"
            with (patch.object(runtime, "is_online", return_value=False),
                  patch.object(runtime, "provision", side_effect=provision),
                  patch("local_ai_hub.llama_cpp_runtime.popen_managed") as popen):
                self.assertFalse(runtime.ensure_running(should_stop=lambda: cancelled[0]))
            popen.assert_not_called()

    def test_mixed_start_does_not_provision_while_fallback_reserves_port(self):
        with tempfile.TemporaryDirectory() as temp:
            port_guard = socket.socket()
            port_guard.bind(("127.0.0.1", 0))
            port_guard.listen(1)
            port = port_guard.getsockname()[1]
            try:
                runtime = LlamaCppManagedRuntime({
                    "server": {"state_dir": temp},
                    "llama_cpp": {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                                  "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate",
                                  "models": {"candidate": {"url": f"http://127.0.0.1:{port}"}}},
                })
                with (patch.object(runtime, "is_online", return_value=False),
                      patch.object(runtime, "provision") as provision):
                    self.assertFalse(runtime.ensure_running())
                provision.assert_not_called()
            finally:
                port_guard.close()

    def test_custom_model_selector_fails_closed_for_invalid_or_unknown_values(self):
        for value in (None, [], "", " candidate", "missing"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temp:
                runtime = LlamaCppManagedRuntime({
                    "server": {"state_dir": temp},
                    "llama_cpp": {"managed_model_sha256": "a" * 64, "managed_model_logical": value,
                                  "models": {"candidate": {"url": "http://127.0.0.1:12438"}}},
                })
                with self.assertRaisesRegex(ValueError, "managed_model_logical"):
                    runtime._configured_routes()

    def test_managed_cuda_response_reports_cuda_provider(self):
        from local_ai_hub.ollama import OllamaRuntime

        with tempfile.TemporaryDirectory() as temp:
            runtime = OllamaRuntime({
                "server": {"state_dir": temp, "ollama_url": "http://127.0.0.1:11434"},
                "ollama": {"enabled": False}, "llama_cpp": {"mode": "on", "backend": "cuda"},
            })
            runtime.llama_cpp = SimpleNamespace(request_stream=lambda *args, **kwargs: {"done": True})
            with patch.object(runtime.llama_cpp_managed, "status", return_value={"mode": "CUDA0"}):
                self.assertEqual(runtime._llama_version_label(), "llama.cpp CUDA")
                response = runtime.request_stream("/api/chat", {"model": "test"}, None, timeout=10)
            self.assertEqual(response["_lah_provider"], "llama.cpp-cuda")

    def test_custom_model_cannot_be_served_under_multiple_logical_model_names(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = LlamaCppManagedRuntime({
                "server": {"state_dir": temp},
                "llama_cpp": {"managed_model_sha256": "a" * 64, "models": {
                    "first": {"url": "http://127.0.0.1:12438", "served_model": "first"},
                    "second": {"url": "http://127.0.0.1:12438", "served_model": "second"},
                }},
            })
            with self.assertRaisesRegex(ValueError, "one logical model"):
                runtime._write_preset()

    def test_config_validation_rejects_invalid_cuda_backend_and_model_digest(self):
        from local_ai_hub.config import ConfigError, validate_config

        validate_config({"llama_cpp": {"backend": "cuda", "managed_model_sha256": "a" * 64}})
        for invalid in ([], None, "CUDA", "bogus"):
            with self.subTest(backend=invalid), self.assertRaises(ConfigError):
                validate_config({"llama_cpp": {"backend": invalid}})
        for invalid in (False, None, "A" * 64, "a" * 63, "z" * 64):
            with self.subTest(digest=invalid), self.assertRaises(ConfigError):
                validate_config({"llama_cpp": {"managed_model_sha256": invalid}})

        route = {"candidate": {"url": "http://127.0.0.1:12438"}}
        validate_config({"llama_cpp": {"managed_model_sha256": "a" * 64, "managed_model_logical": "candidate", "models": route}})
        for invalid in (None, "", " candidate", "missing", [], "vision-vl"):
            with self.subTest(logical=invalid), self.assertRaises(ConfigError):
                validate_config({"llama_cpp": {"managed_model_sha256": "a" * 64, "managed_model_logical": invalid, "models": route}})
        with self.assertRaises(ConfigError):
            validate_config({"llama_cpp": {"managed_model_logical": "candidate", "models": route}})
        valid_mixed = {"mode": "on", "backend": "cuda", "managed_with_ollama": True,
                       "managed_model_sha256": "a" * 64, "managed_model_logical": "candidate", "models": route}
        validate_config({"ollama": {"enabled": True}, "llama_cpp": valid_mixed})
        for invalid in (None, "true", 1):
            with self.subTest(mixed=invalid), self.assertRaises(ConfigError):
                validate_config({"ollama": {"enabled": True}, "llama_cpp": {**valid_mixed, "managed_with_ollama": invalid}})
        for key, value in (("mode", "auto"), ("backend", "auto"), ("managed_model_logical", None)):
            with self.subTest(key=key), self.assertRaises(ConfigError):
                validate_config({"ollama": {"enabled": True}, "llama_cpp": {**valid_mixed, key: value}})
        with self.assertRaises(ConfigError):
            validate_config({"ollama": {"enabled": True}, "smart_ollama": {"enabled": True}, "llama_cpp": valid_mixed})

    def test_custom_managed_model_requires_matching_existing_file_without_downloading_default(self):
        with tempfile.TemporaryDirectory() as temp:
            model_bytes = b"local candidate"
            digest = hashlib.sha256(model_bytes).hexdigest()
            runtime = LlamaCppManagedRuntime({
                "server": {"state_dir": temp},
                "llama_cpp": {"managed_model_filename": "candidate.gguf", "managed_model_sha256": digest},
            })
            runtime.runtime_dir.mkdir(parents=True)
            runtime.model_dir.mkdir(parents=True)
            binary = runtime.runtime_dir / "llama-server.exe"
            binary.write_bytes(b"server")
            _, asset_digest, _ = runtime.runtime_asset()
            (runtime.runtime_dir / ".runtime-sha256").write_text(asset_digest, encoding="utf-8")
            with patch.object(runtime, "_download") as download:
                with self.assertRaisesRegex(RuntimeError, "managed model"):
                    runtime.provision()
                runtime.model_path.write_bytes(b"wrong")
                with self.assertRaisesRegex(RuntimeError, "managed model"):
                    runtime.provision()
                runtime.model_path.write_bytes(model_bytes)
                self.assertEqual(runtime.provision(), binary)
            download.assert_not_called()

    def test_custom_model_refuses_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = LlamaCppManagedRuntime({
                "server": {"state_dir": temp},
                "llama_cpp": {"managed_model_filename": "candidate.gguf", "managed_model_sha256": "a" * 64},
            })
            runtime.runtime_dir.mkdir(parents=True)
            (runtime.runtime_dir / "llama-server.exe").write_bytes(b"server")
            (runtime.runtime_dir / ".runtime-sha256").write_text(runtime.runtime_asset()[1], encoding="utf-8")
            with patch.object(Path, "is_symlink", return_value=True):
                with self.assertRaisesRegex(RuntimeError, "managed model.*link"):
                    runtime.provision()

    def test_cuda_rejects_unsupported_host_and_invalid_backend(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = LlamaCppManagedRuntime({"server": {"state_dir": temp}, "llama_cpp": {"backend": "cuda"}})
            with patch.object(runtime, "_host_platform", return_value=("win32", "amd64")):
                with self.assertRaisesRegex(RuntimeError, "detected NVIDIA GPU"):
                    runtime.provision()
            for invalid in ([], None, "CUDA", "other"):
                with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "backend"):
                    LlamaCppManagedRuntime({"llama_cpp": {"backend": invalid}})

    def test_explicit_cuda_provision_installs_both_verified_archives_in_separate_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = LlamaCppManagedRuntime({
                "server": {"state_dir": temp},
                "llama_cpp": {"backend": "cuda"},
                "_hardware": {"gpus": [{"vendor": "nvidia"}]},
            })
            archives = {}
            for name, member, payload in (
                ("cuda-server.zip", "llama-server.exe", b"server"),
                ("cuda-libs.zip", "cudart64_13.dll", b"runtime"),
            ):
                data = io.BytesIO()
                with zipfile.ZipFile(data, "w") as bundle:
                    bundle.writestr(member, payload)
                archives[name] = data.getvalue()
            specs = tuple((name, hashlib.sha256(data).hexdigest(), "zip") for name, data in archives.items())
            runtime.model_path.parent.mkdir(parents=True)
            runtime.model_path.write_bytes(b"model")

            def download(url, destination, expected_sha256, max_bytes, timeout):
                data = archives[Path(destination).name]
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected_sha256)
                destination.write_bytes(data)

            with (
                patch.object(runtime, "_host_platform", return_value=("win32", "amd64")),
                patch("local_ai_hub.llama_cpp_runtime.CUDA_WINDOWS_X64", specs),
                patch("local_ai_hub.llama_cpp_runtime.MODEL_SHA256", hashlib.sha256(b"model").hexdigest()),
                patch.object(runtime, "_download", side_effect=download),
            ):
                binary = runtime.provision()
            self.assertEqual(binary.read_bytes(), b"server")
            self.assertEqual((binary.parent / "cudart64_13.dll").read_bytes(), b"runtime")
            self.assertIn("cuda", runtime.runtime_dir.name)
            self.assertEqual(runtime._device_attempts(False)[0][0], "CUDA0")
            (binary.parent / "cudart64_13.dll").unlink()
            with (
                patch.object(runtime, "_host_platform", return_value=("win32", "amd64")),
                patch("local_ai_hub.llama_cpp_runtime.CUDA_WINDOWS_X64", specs),
                patch("local_ai_hub.llama_cpp_runtime.MODEL_SHA256", hashlib.sha256(b"model").hexdigest()),
                patch.object(runtime, "_download", side_effect=download),
            ):
                runtime.provision()
            self.assertEqual((binary.parent / "cudart64_13.dll").read_bytes(), b"runtime")

    def test_backend_selection_is_explicit_and_ollama_has_precedence(self):
        self.assertEqual(llama_cpp_backend_selection({"ollama": {"enabled": True}, "llama_cpp": {"mode": "on"}}), "ollama")
        self.assertFalse(llama_cpp_managed_selected({"ollama": {"enabled": True}, "llama_cpp": {"mode": "on"}}))
        self.assertEqual(llama_cpp_backend_selection({"ollama": {"enabled": False}, "llama_cpp": {"mode": "on"}}), "llama.cpp (managed)")
        self.assertTrue(llama_cpp_managed_selected({"ollama": {"enabled": False}, "llama_cpp": {"mode": "on"}}))
        self.assertEqual(llama_cpp_backend_selection({"ollama": {"enabled": False}, "llama_cpp": {"mode": "auto"}}), "llama.cpp (external, auto-detect)")
        self.assertEqual(llama_cpp_backend_selection({"ollama": {"enabled": False}, "llama_cpp": {"mode": "off"}}), "disabled")

    def test_runtime_assets_are_pinned_and_unsupported_platforms_fail(self):
        self.assertEqual(LlamaCppManagedRuntime.runtime_asset("win32", "amd64")[0], "llama-b10964-bin-win-cpu-x64.zip")
        self.assertEqual(LlamaCppManagedRuntime.runtime_asset("darwin", "arm64")[0], "llama-b10964-bin-macos-arm64.tar.gz")
        with self.assertRaisesRegex(RuntimeError, "not supported"):
            LlamaCppManagedRuntime.runtime_asset("freebsd", "x86_64")

    def test_download_requires_expected_sha256_and_removes_partial_files(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "artifact.bin"
            payload = b"verified runtime bytes"
            with patch("local_ai_hub.llama_cpp_runtime.urlopen", return_value=io.BytesIO(payload)):
                LlamaCppManagedRuntime._download("https://example.invalid/artifact", destination, hashlib.sha256(payload).hexdigest(), 100, 1)
            self.assertEqual(destination.read_bytes(), payload)
            destination.unlink()
            with patch("local_ai_hub.llama_cpp_runtime.urlopen", return_value=io.BytesIO(payload)):
                with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                    LlamaCppManagedRuntime._download("https://example.invalid/artifact", destination, "0" * 64, 100, 1)
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_name(destination.name + ".part").exists())

    def test_archive_extraction_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "malicious.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("../outside.txt", "bad")
            with self.assertRaisesRegex(RuntimeError, "Unsafe path"):
                LlamaCppManagedRuntime._extract(archive, Path(temp) / "extract", "zip")
            self.assertFalse((Path(temp) / "outside.txt").exists())

    def test_preset_maps_configured_text_aliases_to_verified_default_model(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = LlamaCppManagedRuntime({
                "server": {"state_dir": temp},
                "models": {"fast_code": "qwen2.5-coder:1.5b"},
                "llama_cpp": {"models": {
                    "qwen2.5-coder:1.5b": {"served_model": "hub-qwen-15", "url": "http://127.0.0.1:12438"},
                    "qwen2.5-coder:3b": {"served_model": "hub-qwen-3", "url": "http://127.0.0.1:12438"},
                    "qwen3-vl:4b": {"served_model": "hub-qwen-vl", "url": "http://127.0.0.1:12438"},
                }},
            })
            runtime._write_preset()
            preset = (runtime.runtime_dir / "hub.models.ini").read_text(encoding="utf-8")
            self.assertIn("[hub-qwen-15]", preset)
            self.assertIn("[hub-qwen-3]", preset)
            self.assertNotIn("[hub-qwen-vl]", preset)
            model_path = runtime.model_path.resolve().as_posix()
            self.assertIn(f"model = {model_path}", preset)
            self.assertNotIn(f'model = "{model_path}"', preset)
            self.assertIn("load-on-startup = true", preset)
            self.assertIn("load-on-startup = false", preset)
            runtime._write_preset(device="SYCL0")
            preset = (runtime.runtime_dir / "hub.models.ini").read_text(encoding="utf-8")
            self.assertIn("[*]\nn-gpu-layers = 99\ndevice = SYCL0\nmodels-max = 1", preset)
            runtime._write_preset(device="none")
            preset = (runtime.runtime_dir / "hub.models.ini").read_text(encoding="utf-8")
            self.assertIn("device = none", preset)

    def test_intel_start_retries_on_cpu_after_sycl_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = LlamaCppManagedRuntime({
                "server": {"state_dir": temp},
                "_hardware": {"gpus": [{"vendor": "Intel", "name": "Intel Arc"}]},
                "models": {"fast_code": "qwen2.5-coder:1.5b"},
                "llama_cpp": {"mode": "on", "startup_timeout_seconds": 3, "models": {
                    "qwen2.5-coder:1.5b": {"served_model": "hub-qwen-15", "url": "http://127.0.0.1:12438"},
                }},
            })
            processes = []

            class FakeProc:
                def __init__(self, pid):
                    self.pid = pid
                    self.wait_calls = 0

                def poll(self):
                    return None

                def wait(self, timeout=None):
                    self.wait_calls += 1
                    return -9

            def fake_popen(*_args, **_kwargs):
                process = FakeProc(42 + len(processes))
                processes.append(process)
                return process

            with (
                patch.object(runtime, "is_online", return_value=False),
                patch.object(runtime, "provision", return_value=runtime.runtime_dir / "bin" / "llama-server.exe"),
                patch.object(runtime, "_find_server", return_value=runtime.runtime_dir / "bin" / "llama-server.exe"),
                patch.object(runtime, "_device_attempts", return_value=[("SYCL0", 0.1), ("none", 0.1)]),
                patch.object(runtime, "_write_preset") as write_preset,
                patch.object(runtime, "_ready", side_effect=[False, True]),
                patch("local_ai_hub.llama_cpp_runtime.popen_managed", side_effect=fake_popen) as popen,
                patch("local_ai_hub.llama_cpp_runtime.terminate_tree", return_value=True),
            ):
                self.assertTrue(runtime.ensure_running())
            self.assertEqual(popen.call_count, 2)
            self.assertEqual(popen.call_args_list[0].args[0][-1], "SYCL0")
            self.assertEqual(popen.call_args_list[0].kwargs["env"]["GGML_SYCL_ENABLE_VMM"], "0")
            self.assertEqual(popen.call_args_list[1].args[0][-1], "none")
            self.assertNotIn("env", popen.call_args_list[1].kwargs)
            self.assertEqual(write_preset.call_args_list, [call(device="SYCL0"), call(device="none")])
            self.assertEqual(processes[0].wait_calls, 1)
            self.assertEqual(runtime.mode_path.read_text(encoding="utf-8"), "none")

    def test_install_and_update_guidance_share_provider_selection_policy(self):
        for relative in ("docs/INSTALLATION.md", "docs/OPERATIONS.md", "docs/INSTALL_PROMPT.md", "docs/UPDATE_PROMPT.md", "docs/LLAMA_CPP_SYCL.md"):
            guidance = (ROOT / relative).read_text(encoding="utf-8").lower()
            self.assertIn('llama_cpp.mode = "on"', guidance, relative)
            self.assertIn('"auto"', guidance, relative)
            self.assertNotIn("never installs or starts llama.cpp automatically", guidance, relative)


if __name__ == "__main__":
    unittest.main()
