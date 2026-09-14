from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.budget import estimate_tokens
from local_ai_hub.model_policy import ModelExecutionPolicy
from local_ai_hub.router import ModelRouter
from local_ai_hub.services import LocalAIServices, _split_review_diff


class ReviewDiffChunkingTests(unittest.TestCase):
    def _services(self, diff_text, estimated_tokens, changed_files=None):
        services = MagicMock(spec=LocalAIServices)
        config = {
            "models": {
                "fast_code": "qwen2.5-coder:3b-instruct-q5_K_M",
                "heavy_code": "qwen2.5-coder:7b-instruct-q5_K_M",
                "reasoning": "qwen2.5-coder:7b-instruct-q5_K_M",
                "general": "qwen2.5-coder:3b-instruct-q5_K_M",
            },
            "routing": {"prefer_resident_model": False},
            "model_execution": {
                "fast": {"context_tokens": 8192, "large_context_tokens": 8192, "max_context_tokens": 8192},
                "smart": {"context_tokens": 8192, "large_context_tokens": 8192, "max_context_tokens": 8192},
            },
            "token_saving": {"max_local_input_tokens": 8192, "max_local_output_tokens": 2400},
        }
        services.config = config
        services.router = ModelRouter(config)
        services.model_policy = ModelExecutionPolicy(config)
        services._resident_optimize = lambda route, task_type, complexity: route
        services.vram_balancer = None
        services.deterministic = MagicMock()
        services.deterministic.diff_facts.return_value = {
            "risk": {"level": "low", "score": 0},
            "breaking_changes": [],
        }
        services.repo_diff.return_value = {
            "success": True,
            "diff": diff_text,
            "changed_files": changed_files or ["sample.py"],
            "truncated": False,
            "estimated_tokens": estimated_tokens,
            "original_estimated_tokens": estimated_tokens,
        }
        return services

    def test_small_diff_stays_single_request(self):
        diff_text = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new\n"
        services = self._services(diff_text, estimate_tokens(diff_text))
        calls = []
        services.delegate = lambda payload, tenant: calls.append(payload) or {
            "success": True, "text": "No findings.", "model": "3b"
        }

        result = LocalAIServices.review_diff(services, {"root": "."}, "test")

        self.assertTrue(result["success"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["context"], diff_text)
        self.assertEqual(calls[0]["complexity"], "fast")
        self.assertEqual(result["diff"]["review_chunks"], 1)

    def test_large_hunk_is_split_under_budget_and_keeps_heavy_route(self):
        changed_lines = [f"+    value_{index} = {index}  # changed\n" for index in range(500)]
        diff_text = (
            "diff --git a/sample.py b/sample.py\n"
            "index 0000000..1111111 100644\n"
            "--- a/sample.py\n+++ b/sample.py\n"
            f"@@ -1,0 +1,{len(changed_lines)} @@\n"
            + "".join(changed_lines)
        )
        services = self._services(diff_text, estimate_tokens(diff_text))
        calls = []
        services.delegate = lambda payload, tenant: calls.append(payload) or {
            "success": True, "text": "No actionable finding.", "model": "7b"
        }

        result = LocalAIServices.review_diff(services, {"root": "."}, "test")

        self.assertTrue(result["success"])
        segment_calls = [call for call in calls if call["context"].startswith("diff --git")]
        self.assertGreater(len(segment_calls), 1)
        self.assertTrue(
            all(
                estimate_tokens(call["context"]) <= result["diff"]["review_chunk_token_budget"]
                for call in segment_calls
            )
        )
        self.assertTrue(all(call["complexity"] == "heavy" for call in calls))
        self.assertTrue(all(call["max_tokens"] <= 700 for call in segment_calls))
        self.assertTrue(result["review_synthesis"]["enabled"])
        self.assertFalse(result["review_synthesis"]["degraded"])
        self.assertEqual(result["diff"]["review_chunks"], len(segment_calls))
        self.assertLessEqual(
            result["diff"]["largest_review_chunk_tokens"],
            result["diff"]["review_chunk_token_budget"],
        )
        self.assertEqual(
            [line for call in segment_calls for line in call["context"].splitlines()
             if line.startswith("+") and not line.startswith("+++")],
            [line.rstrip("\r\n") for line in changed_lines],
        )

    def test_file_and_hunk_boundaries_are_preserved(self):
        one_file = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n"
        two_file = "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -2 +2 @@\n-c\n+d\n"
        chunks = _split_review_diff(one_file + two_file, max_tokens=256)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], one_file + two_file)

    def test_many_small_files_are_packed_by_tokens_not_file_count(self):
        diff_text = "".join(
            f"diff --git a/file_{i}.py b/file_{i}.py\n--- a/file_{i}.py\n+++ b/file_{i}.py\n"
            f"@@ -1 +1 @@\n-value = {i}\n+value = {i + 1}\n"
            for i in range(30)
        )
        services = self._services(
            diff_text, estimate_tokens(diff_text), changed_files=[f"file_{i}.py" for i in range(30)]
        )
        services.config["model_execution"]["smart"].update(
            {"context_tokens": 16384, "large_context_tokens": 16384, "max_context_tokens": 16384}
        )
        services.config["token_saving"]["max_local_input_tokens"] = 56000
        services.model_policy = ModelExecutionPolicy(services.config)
        calls = []
        services.delegate = lambda payload, tenant: calls.append(payload) or {
            "success": True, "text": "No findings.", "model": "3b"
        }

        result = LocalAIServices.review_diff(services, {"root": "."}, "test")

        self.assertTrue(result["success"])
        segment_calls = [call for call in calls if call["context"].startswith("diff --git")]
        self.assertEqual(len(segment_calls), 1)
        self.assertEqual(result["diff"]["review_chunks"], 1)
        self.assertEqual(result["diff"]["review_model"], "qwen2.5-coder:7b-instruct-q5_K_M")
        self.assertGreater(result["diff"]["review_chunk_token_budget"], 2400)
        self.assertLessEqual(
            result["diff"]["review_chunk_token_budget"],
            result["diff"]["effective_prompt_budget_tokens"] * 0.5,
        )

    def test_consensus_reviews_each_large_diff_segment(self):
        changed_lines = [f"+    value_{index} = {index}\n" for index in range(500)]
        diff_text = (
            "diff --git a/sample.py b/sample.py\n--- a/sample.py\n+++ b/sample.py\n"
            f"@@ -1,0 +1,{len(changed_lines)} @@\n"
            + "".join(changed_lines)
        )
        services = self._services(diff_text, estimate_tokens(diff_text))
        calls = []

        def fake_delegate(payload, tenant):
            calls.append(payload)
            return {
                "success": True,
                "text": f"{payload['task_type']} checked.",
                "model": "7b" if payload["task_type"] == "review" else "reasoning-7b",
            }

        services.delegate = fake_delegate
        result = LocalAIServices.review_diff(
            services, {"root": ".", "consensus": True}, "test"
        )

        chunk_count = result["diff"]["review_chunks"]
        self.assertGreater(chunk_count, 1)
        primary_segments = [
            call for call in calls
            if call["task_type"] == "review" and call["context"].startswith("diff --git")
        ]
        counter_segments = [
            call for call in calls
            if call["task_type"] == "reasoning" and call["context"].startswith("diff --git")
        ]
        self.assertEqual(len(primary_segments), chunk_count)
        self.assertEqual(len(counter_segments), chunk_count)
        self.assertEqual(len(calls), chunk_count * 2 + 2)
        self.assertEqual(result["consensus"]["enabled"], True)
        self.assertEqual(result["consensus"]["secondary_model"], "reasoning-7b")
        self.assertTrue(result["consensus"]["synthesis"]["enabled"])

    def test_unsplittable_large_line_is_rejected_instead_of_exceeding_budget(self):
        diff_text = (
            "diff --git a/minified.js b/minified.js\n--- a/minified.js\n+++ b/minified.js\n"
            "@@ -1 +1 @@\n-" + "a" * 9000 + "\n+" + "b" * 9000 + "\n"
        )
        services = self._services(diff_text, estimate_tokens(diff_text))
        services.delegate = MagicMock(return_value={"success": True, "text": "Should not run."})

        result = LocalAIServices.review_diff(services, {"root": "."}, "test")

        self.assertFalse(result["success"])
        self.assertIn("cannot be split safely", result["error"])
        services.delegate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
