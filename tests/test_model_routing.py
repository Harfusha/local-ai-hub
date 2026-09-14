from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.router import ModelRouter, review_diff_complexity


class ReviewDiffRoutingTests(unittest.TestCase):
    def test_basic_reasoning_uses_fast_and_complex_reasoning_escalates(self):
        router = ModelRouter(
            {
                "models": {
                    "fast_code": "qwen2.5-coder:3b",
                    "heavy_code": "qwen2.5-coder:7b",
                    "reasoning": "qwen2.5-coder:7b",
                    "general": "qwen2.5-coder:3b",
                }
            }
        )

        basic = router.classify("Explain this behavior", task_type="reasoning")
        complex_route = router.classify(
            "Analyze the root cause", task_type="reasoning", complexity="heavy"
        )

        self.assertEqual(basic["model"], "qwen2.5-coder:3b")
        self.assertEqual(complex_route["model"], "qwen2.5-coder:7b")

    def test_model_override_requires_a_configured_tier(self):
        router = ModelRouter(
            {"models": {"background_code": "qwen2.5-coder:1.5b", "fast_code": "qwen2.5-coder:3b", "heavy_code": "qwen2.5-coder:7b"}}
        )
        route = router.classify("Complete this function", task_type="code")

        overridden = router.apply_model_override(route, "qwen2.5-coder:7b")
        self.assertEqual(overridden["model"], "qwen2.5-coder:7b")
        self.assertEqual(overridden["original_model"], "qwen2.5-coder:3b")
        with self.assertRaisesRegex(ValueError, "configured model tier"):
            router.apply_model_override(route, "qwen2.5-coder:9b")
        with self.assertRaisesRegex(ValueError, "configured model tier"):
            router.apply_model_override(route, "qwen2.5-coder:1.5b")

    def test_high_risk_metadata_escalates_to_heavy_model(self):
        complexity = review_diff_complexity(
            {}, {"risk_score": 75, "risk_level": "high"}, {"changed_files": ["a.py"]}
        )
        router = ModelRouter(
            {
                "models": {"fast_code": "3b", "heavy_code": "7b", "general": "3b"},
                "routing": {"review_heavy_min_score": 3},
            }
        )

        route = router.classify("Review this diff", task_type="review", complexity=complexity)

        self.assertEqual(complexity, "heavy")
        self.assertEqual(route["model"], "7b")

    def test_large_diff_escalates_but_explicit_fast_is_respected(self):
        diff = {"changed_files": [f"file-{index}.py" for index in range(6)]}
        self.assertEqual(review_diff_complexity({}, {}, diff), "heavy")
        self.assertEqual(
            review_diff_complexity({"complexity": "fast"}, {"risk_level": "critical"}, diff),
            "fast",
        )

    def test_small_low_risk_diff_keeps_auto_routing(self):
        self.assertEqual(review_diff_complexity({}, {}, {"changed_files": ["one.py"]}), "auto")


if __name__ == "__main__":
    unittest.main()
