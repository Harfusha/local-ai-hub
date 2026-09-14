from pathlib import Path
import sys
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.router import ModelRouter, review_diff_complexity
from local_ai_hub.services import LocalAIServices


class ReasonTaskNormalizationTests(unittest.TestCase):
    def test_reason_accepts_prompt_and_routes_to_reasoning_tier(self):
        class DelegateCapture:
            def delegate(self, args, tenant):
                return args

        args = LocalAIServices.reason(
            DelegateCapture(), {"prompt": "Analyze this failure", "complexity": "auto"}, "test"
        )
        router = ModelRouter({"models": {
            "background_code": "qwen2.5-coder:0.5b",
            "fast_code": "qwen2.5-coder:1.5b",
            "heavy_code": "qwen2.5-coder:3b",
            "reasoning": "qwen2.5-coder:7b",
            "general": "qwen2.5-coder:1.5b",
        }})

        self.assertEqual(args["task"], "Analyze this failure")
        self.assertEqual(args["task_type"], "reasoning")
        self.assertEqual(
            router.classify(args["task"], task_type=args["task_type"], complexity=args["complexity"])["model"],
            "qwen2.5-coder:7b",
        )


class DefaultModelTierConfigTests(unittest.TestCase):
    def test_packaged_default_configs_expose_all_four_roles_and_aliases(self):
        expected_models = {
            "background_code": "qwen2.5-coder:0.5b",
            "fast_code": "qwen2.5-coder:1.5b",
            "heavy_code": "qwen2.5-coder:3b",
            "reasoning": "qwen2.5-coder:7b",
            "general": "qwen2.5-coder:1.5b",
        }
        expected_aliases = {
            "qwen2.5-coder:0.5b": "hub-qwen-05",
            "qwen2.5-coder:1.5b": "hub-qwen-15",
            "qwen2.5-coder:3b": "hub-qwen-3",
            "qwen2.5-coder:7b": "hub-qwen-7",
        }
        for path in (ROOT / "defaults.toml", ROOT / "src/local_ai_hub/defaults.toml"):
            with self.subTest(path=path):
                config = tomllib.loads(path.read_text(encoding="utf-8"))
                self.assertEqual({key: config["models"][key] for key in expected_models}, expected_models)
                actual_aliases = {
                    tag: entry["served_model"]
                    for tag, entry in config["llama_cpp"]["models"].items()
                }
                self.assertEqual(actual_aliases, expected_aliases)


class ReviewDiffRoutingTests(unittest.TestCase):
    def test_all_reasoning_uses_heavy_tier(self):
        router = ModelRouter(
            {
                "models": {
                    "fast_code": "qwen2.5-coder:1.5b",
                    "heavy_code": "qwen2.5-coder:3b",
                    "reasoning": "qwen2.5-coder:7b",
                    "general": "qwen2.5-coder:1.5b",
                }
            }
        )

        basic = router.classify("Explain this behavior", task_type="reasoning")
        complex_route = router.classify(
            "Analyze the root cause", task_type="reasoning", complexity="heavy"
        )

        self.assertEqual(basic["model"], "qwen2.5-coder:7b")
        self.assertEqual(complex_route["model"], "qwen2.5-coder:7b")

    def test_model_override_requires_a_configured_tier(self):
        router = ModelRouter(
                {"models": {"background_code": "qwen2.5-coder:0.5b", "fast_code": "qwen2.5-coder:1.5b", "heavy_code": "qwen2.5-coder:3b", "reasoning": "qwen2.5-coder:7b"}}
        )
        route = router.classify("Complete this function", task_type="code")

        overridden = router.apply_model_override(route, "qwen2.5-coder:7b")
        self.assertEqual(overridden["model"], "qwen2.5-coder:7b")
        self.assertEqual(overridden["original_model"], "qwen2.5-coder:1.5b")
        self.assertEqual(router.apply_model_override(route, "qwen2.5-coder:1.5b")["model"], "qwen2.5-coder:1.5b")
        self.assertEqual(router.apply_model_override(route, "qwen2.5-coder:3b")["model"], "qwen2.5-coder:3b")
        with self.assertRaisesRegex(ValueError, "configured model tier"):
            router.apply_model_override(route, "qwen2.5-coder:9b")
        with self.assertRaisesRegex(ValueError, "configured model tier"):
            router.apply_model_override(route, "qwen2.5-coder:0.5b")

    def test_four_default_roles_map_to_expected_tiers(self):
        router = ModelRouter({"models": {
            "background_code": "qwen2.5-coder:0.5b",
            "fast_code": "qwen2.5-coder:1.5b",
            "heavy_code": "qwen2.5-coder:3b",
            "reasoning": "qwen2.5-coder:7b",
            "general": "qwen2.5-coder:1.5b",
        }})
        self.assertEqual(router.classify("Complete this function", task_type="code")["model"], "qwen2.5-coder:1.5b")
        self.assertEqual(router.classify("Complete this function", task_type="code", complexity="heavy")["model"], "qwen2.5-coder:3b")
        self.assertEqual(router.classify("Explain this", task_type="reasoning")["model"], "qwen2.5-coder:7b")
        self.assertEqual(router.classify("Summarize this", task_type="general")["model"], "qwen2.5-coder:1.5b")

    def test_high_risk_metadata_escalates_to_heavy_model(self):
        complexity = review_diff_complexity(
            {}, {"risk_score": 75, "risk_level": "high"}, {"changed_files": ["a.py"]}
        )
        router = ModelRouter(
            {
                "models": {"fast_code": "7b", "heavy_code": "7b", "general": "7b"},
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
