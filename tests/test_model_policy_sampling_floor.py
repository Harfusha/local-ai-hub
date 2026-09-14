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
                "background_code": "qwen2.5-coder:1.5b-instruct-q5_K_M",
                "fast_code": "qwen2.5-coder:3b-instruct-q5_K_M",
                "heavy_code": "qwen2.5-coder:7b-instruct-q5_K_M",
                "reasoning": "qwen2.5-coder:7b-instruct-q5_K_M",
            }
        })

    def test_positive_near_greedy_temperature_is_raised_for_7b(self):
        payload, _ = self.policy.apply_payload(
            "qwen2.5-coder:7b-instruct-q5_K_M",
            {"options": {"temperature": 0.05}},
            role="reasoning",
        )
        self.assertEqual(payload["options"]["temperature"], 0.2)

    def test_explicit_zero_temperature_remains_deterministic(self):
        payload, _ = self.policy.apply_payload(
            "qwen2.5-coder:7b-instruct-q5_K_M",
            {"options": {"temperature": 0.0}},
            role="reasoning",
        )
        self.assertEqual(payload["options"]["temperature"], 0.0)


if __name__ == "__main__":
    unittest.main()
