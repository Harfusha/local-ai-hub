from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.hardware import profile_overrides
from local_ai_hub.llama_cpp import LlamaCppRouter, _loopback_url


class _Response:
    status = 200

    def __init__(self, value: dict | None = None, lines: list[bytes] | None = None):
        self.value = value or {}
        self.lines = lines or []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.value).encode("utf-8")

    def __iter__(self):
        return iter(self.lines)


class LlamaCppRoutingTests(unittest.TestCase):
    def _config(self, vendor: str = "intel", mode: str = "auto") -> dict:
        return {
            "server": {"request_timeout_seconds": 10},
            "_hardware": {"gpus": [{"vendor": vendor, "name": f"{vendor} GPU", "integrated": True}]},
            "llama_cpp": {
                "mode": mode,
                "models": {
                    "qwen2.5-coder:0.5b": {"url": "http://127.0.0.1:12438", "served_model": "hub-qwen-05", "context_length": 16384},
                    "qwen2.5-coder:1.5b": {"url": "http://127.0.0.1:12438", "served_model": "hub-qwen-15", "context_length": 32768},
                    "qwen2.5-coder:3b": {"url": "http://127.0.0.1:12438", "served_model": "hub-qwen-3", "context_length": 32768},
                    "qwen2.5-coder:7b": {"url": "http://127.0.0.1:12438", "served_model": "hub-qwen-7", "context_length": 32768},
                },
            },
        }

    def test_auto_route_is_intel_only_and_explicit_on_is_opt_in(self):
        self.assertTrue(LlamaCppRouter(self._config("intel"))._hardware_allows())
        self.assertFalse(LlamaCppRouter(self._config("amd"))._hardware_allows())
        self.assertFalse(LlamaCppRouter(self._config("nvidia"))._hardware_allows())
        self.assertTrue(LlamaCppRouter(self._config("nvidia", "on"))._hardware_allows())

    def test_auto_does_not_take_over_when_dedicated_other_gpu_is_present(self):
        config = self._config()
        config["_hardware"]["gpus"].append({"vendor": "nvidia", "name": "RTX", "integrated": False})
        self.assertFalse(LlamaCppRouter(config)._hardware_allows())

    def test_router_mode_stream_translates_generate_and_chat(self):
        router = LlamaCppRouter(self._config())
        lines = [
            b'data: {"choices":[{"delta":{"content":"PASS-27"},"finish_reason":null}]}\n',
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":12,"completion_tokens":1}}\n',
            b"data: [DONE]\n",
        ]

        def fake_urlopen(req, timeout=0):
            if req.full_url.endswith("/health"):
                return _Response({"status": "ok"})
            if req.full_url.endswith("/models"):
                rows = [{"id": entry["served_model"], "status": {"value": "loaded"}} for entry in self._config()["llama_cpp"]["models"].values()]
                return _Response({"data": rows})
            if req.full_url.endswith("/v1/chat/completions"):
                body = json.loads(req.data.decode("utf-8"))
                self.assertEqual(body["model"], "hub-qwen-3")
                self.assertEqual(body["messages"][-1]["content"], "reply only PASS-27")
                return _Response(lines=lines)
            self.fail(f"unexpected URL: {req.full_url}")

        chunks: list[str] = []
        with patch("local_ai_hub.llama_cpp.urlopen", side_effect=fake_urlopen):
            result = router.request_stream(
                "/api/generate",
                {"model": "qwen2.5-coder:3b", "system": "be exact", "prompt": "reply only PASS-27", "options": {"num_predict": 8, "temperature": 0}},
                chunks.append,
                timeout=2,
            )
        self.assertEqual(result["response"], "PASS-27")
        self.assertEqual(result["prompt_eval_count"], 12)
        self.assertEqual(chunks, ["PASS-27"])
        self.assertEqual(result["_lah_provider"], "llama.cpp-sycl")

    def test_preprocessing_model_uses_stable_half_billion_alias(self):
        router = LlamaCppRouter(self._config())
        lines = [
            b'data: {"choices":[{"delta":{"content":"PREPROCESS-OK"},"finish_reason":null}]}\n',
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n',
            b"data: [DONE]\n",
        ]

        def fake_urlopen(req, timeout=0):
            if req.full_url.endswith("/health"):
                return _Response({"status": "ok"})
            if req.full_url.endswith("/models"):
                rows = [{"id": entry["served_model"], "status": {"value": "loaded"}} for entry in self._config()["llama_cpp"]["models"].values()]
                return _Response({"data": rows})
            if req.full_url.endswith("/v1/chat/completions"):
                body = json.loads(req.data.decode("utf-8"))
                self.assertEqual(body["model"], "hub-qwen-05")
                return _Response(lines=lines)
            self.fail(f"unexpected URL: {req.full_url}")

        with patch("local_ai_hub.llama_cpp.urlopen", side_effect=fake_urlopen):
            result = router.request_stream(
                "/api/generate",
                {"model": "qwen2.5-coder:0.5b", "prompt": "brief factual card", "options": {"num_predict": 8}},
                lambda _text: None,
                timeout=2,
            )
        self.assertEqual(result["response"], "PREPROCESS-OK")
        self.assertEqual(result["_lah_provider"], "llama.cpp-sycl")

    def test_router_tool_call_arguments_are_returned_in_ollama_shape(self):
        router = LlamaCppRouter(self._config())
        lines = [
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"local_ai_repo","arguments":"{\\\"action\\\":\\\"search\\\"}"}}]},"finish_reason":null}]}\n',
            b'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n',
            b"data: [DONE]\n",
        ]

        def fake_urlopen(req, timeout=0):
            if req.full_url.endswith("/health"):
                return _Response({"status": "ok"})
            if req.full_url.endswith("/models"):
                return _Response({"data": [{"id": "hub-qwen-3", "status": {"value": "loaded"}}]})
            if req.full_url.endswith("/v1/chat/completions"):
                return _Response(lines=lines)
            self.fail(f"unexpected URL: {req.full_url}")

        with patch("local_ai_hub.llama_cpp.urlopen", side_effect=fake_urlopen):
            result = router.request_stream("/api/chat", {"model": "qwen2.5-coder:3b", "messages": []}, lambda _text: None, timeout=2)
        call = result["message"]["tool_calls"][0]
        self.assertEqual(call["id"], "c1")
        self.assertEqual(call["function"]["name"], "local_ai_repo")
        self.assertEqual(call["function"]["arguments"], {"action": "search"})

    def test_context_over_limit_falls_back_without_sending_request(self):
        router = LlamaCppRouter(self._config())
        result = router.request_stream(
            "/api/generate",
            {"model": "qwen2.5-coder:3b", "prompt": "x", "options": {"num_ctx": 32769}},
            lambda _text: None,
        )
        self.assertIn("_lah_backend_unavailable", result)

    def test_only_loopback_endpoints_are_accepted(self):
        self.assertEqual(_loopback_url("http://127.0.0.1:12438"), "http://127.0.0.1:12438")
        self.assertEqual(_loopback_url("http://example.com:12438"), "")
        self.assertEqual(_loopback_url("http://localhost:12438/prefix"), "")

    def test_intel_integrated_profile_disables_ollama_vulkan_but_amd_keeps_it(self):
        intel = profile_overrides("integrated", {"gpus": [{"vendor": "intel", "integrated": True}], "ram": {"total_gb": 32}})
        amd = profile_overrides("integrated", {"gpus": [{"vendor": "amd", "integrated": True}], "ram": {"total_gb": 32}})
        self.assertFalse(intel["ollama"]["allow_integrated_gpu"])
        self.assertFalse(intel["ollama"]["enable_vulkan"])
        self.assertTrue(amd["ollama"]["allow_integrated_gpu"])
        self.assertTrue(amd["ollama"]["enable_vulkan"])

    def test_hardware_profiles_share_the_four_model_roles(self):
        expected = {
            "background_code": "qwen2.5-coder:0.5b",
            "fast_code": "qwen2.5-coder:1.5b",
            "heavy_code": "qwen2.5-coder:3b",
            "reasoning": "qwen2.5-coder:7b",
            "general": "qwen2.5-coder:1.5b",
        }
        for name in ("cpu", "integrated", "low", "balanced", "high", "max"):
            with self.subTest(profile=name):
                profile = profile_overrides(name, {"gpus": [], "ram": {"total_gb": 32}})
                self.assertEqual(profile["models"], expected)


if __name__ == "__main__":
    unittest.main()
