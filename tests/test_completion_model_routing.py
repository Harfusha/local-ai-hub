from __future__ import annotations

import unittest

from local_ai_hub.services import LocalAIServices


class CaptureScheduler:
    def submit(self, model, _tenant, _label, operation):
        self.model = model
        return operation()


class ImmediateCache:
    def get_or_compute(self, _key, compute):
        return compute(), False, False


class CaptureRuntime:
    def __init__(self, result=None):
        self.result = result or {"response": "completion"}

    def request(self, _endpoint, payload, timeout=None):
        self.model = payload["model"]
        return self.result


class CompletionModelRoutingTests(unittest.TestCase):
    def test_code_completion_uses_fast_model_not_preprocessing_model(self):
        services = object.__new__(LocalAIServices)
        services.config = {"models": {
            "background_code": "qwen2.5-coder:0.5b",
            "fast_code": "qwen2.5-coder:3b",
        }}
        services.scheduler = CaptureScheduler()
        services.runtime = CaptureRuntime()
        services.generation_cache = ImmediateCache()

        result = services.complete_code({"prefix": "def answer():"}, "test")

        self.assertEqual(result["model"], "qwen2.5-coder:3b")
        self.assertEqual(services.runtime.model, "qwen2.5-coder:3b")

    def test_code_completion_falls_back_to_fast_default(self):
        services = object.__new__(LocalAIServices)
        services.config = {"models": {"background_code": "qwen2.5-coder:0.5b"}}
        services.scheduler = CaptureScheduler()
        services.runtime = CaptureRuntime()
        services.generation_cache = ImmediateCache()

        result = services.complete_code({"prefix": "def answer():"}, "test")

        self.assertEqual(result["model"], "qwen2.5-coder:3b")

    def test_code_completion_rejects_empty_completion(self):
        services = object.__new__(LocalAIServices)
        services.config = {"models": {}}
        services.scheduler = CaptureScheduler()
        services.runtime = CaptureRuntime({"response": "  "})
        services.generation_cache = ImmediateCache()

        result = services.complete_code({"prefix": "def answer():"}, "test")

        self.assertFalse(result["success"])
        self.assertFalse(result.get("completion"))

    def test_code_completion_rejects_null_completion(self):
        services = object.__new__(LocalAIServices)
        services.config = {"models": {}}
        services.scheduler = CaptureScheduler()
        services.runtime = CaptureRuntime({"response": None})
        services.generation_cache = ImmediateCache()

        result = services.complete_code({"prefix": "def answer():"}, "test")

        self.assertFalse(result["success"])
        self.assertFalse(result.get("completion"))

    def test_code_completion_is_not_marked_validated(self):
        services = object.__new__(LocalAIServices)
        services.config = {"models": {}}
        services.scheduler = CaptureScheduler()
        services.runtime = CaptureRuntime({"response": "return 42"})
        services.generation_cache = ImmediateCache()

        result = services.complete_code({"prefix": "def answer():"}, "test")

        self.assertTrue(result["success"])
        self.assertFalse(result["validated"])

    def test_code_completion_reports_unavailable_runtime(self):
        services = object.__new__(LocalAIServices)
        services.config = {"models": {}}
        services.scheduler = CaptureScheduler()
        services.runtime = CaptureRuntime({"error": "runtime unavailable"})
        services.generation_cache = ImmediateCache()

        result = services.complete_code({"prefix": "def answer():"}, "test")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "runtime unavailable")


if __name__ == "__main__":
    unittest.main()
