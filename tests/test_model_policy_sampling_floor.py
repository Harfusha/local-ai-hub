from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.model_policy import ModelExecutionPolicy


class ModelPolicySamplingFloorTests(unittest.TestCase):
    def setUp(self):
        self.policy = ModelExecutionPolicy({
            "models": {
                "background_code": "qwen2.5-coder:0.5b",
                "fast_code": "qwen2.5-coder:1.5b",
                "heavy_code": "qwen2.5-coder:3b",
                "reasoning": "qwen2.5-coder:7b",
            }
        })

    def test_positive_near_greedy_temperature_is_raised_for_7b(self):
        payload, _ = self.policy.apply_payload(
            "qwen2.5-coder:7b",
            {"options": {"temperature": 0.05}},
            role="reasoning",
        )
        self.assertEqual(payload["options"]["temperature"], 0.2)

    def test_explicit_zero_temperature_remains_deterministic(self):
        payload, _ = self.policy.apply_payload(
            "qwen2.5-coder:7b",
            {"options": {"temperature": 0.0}},
            role="reasoning",
        )
        self.assertEqual(payload["options"]["temperature"], 0.0)

    def test_models_are_assigned_to_four_execution_tiers(self):
        self.assertEqual(self.policy.tier_for("qwen2.5-coder:0.5b"), "background")
        self.assertEqual(self.policy.tier_for("qwen2.5-coder:1.5b"), "fast")
        self.assertEqual(self.policy.tier_for("qwen2.5-coder:3b"), "smart")
        self.assertEqual(self.policy.tier_for("qwen2.5-coder:7b"), "smart")


if __name__ == "__main__":
    unittest.main()
