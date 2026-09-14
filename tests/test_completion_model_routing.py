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
    def request(self, _endpoint, payload, timeout=None):
        self.model = payload["model"]
        return {"response": "completion"}


class CompletionModelRoutingTests(unittest.TestCase):
    def test_code_completion_uses_fast_model_not_preprocessing_model(self):
        services = object.__new__(LocalAIServices)
        services.config = {"models": {
            "background_code": "qwen2.5-coder:1.5b-instruct-q5_K_M",
            "fast_code": "qwen2.5-coder:3b-instruct-q5_K_M",
        }}
        services.scheduler = CaptureScheduler()
        services.runtime = CaptureRuntime()
        services.generation_cache = ImmediateCache()

        result = services.complete_code({"prefix": "def answer():"}, "test")

        self.assertEqual(result["model"], "qwen2.5-coder:3b-instruct-q5_K_M")
        self.assertEqual(services.runtime.model, "qwen2.5-coder:3b-instruct-q5_K_M")

    def test_code_completion_falls_back_to_fast_default(self):
        services = object.__new__(LocalAIServices)
        services.config = {"models": {"background_code": "qwen2.5-coder:1.5b-instruct-q5_K_M"}}
        services.scheduler = CaptureScheduler()
        services.runtime = CaptureRuntime()
        services.generation_cache = ImmediateCache()

        result = services.complete_code({"prefix": "def answer():"}, "test")

        self.assertEqual(result["model"], "qwen2.5-coder:3b-instruct-q5_K_M")


if __name__ == "__main__":
    unittest.main()
