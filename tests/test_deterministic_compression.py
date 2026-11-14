import unittest

from local_ai_hub.diagnostic_compression import compress_diagnostic_text
from local_ai_hub.deterministic import DeterministicEngine


class DiagnosticCompressionTests(unittest.TestCase):
    def test_empty_input_keeps_success_shape(self):
        self.assertEqual(
            compress_diagnostic_text(""),
            {"success": True, "text": "", "confidence": 1.0, "deterministic": True},
        )

    def test_narrative_without_diagnostics_is_rejected(self):
        result = compress_diagnostic_text("A calm day in the garden.\nThe sun is warm.")

        self.assertEqual(result, {"success": False, "confidence": 0.2, "reason": "narrative/non-diagnostic input"})

    def test_diagnostic_lines_keep_context_and_original_numbers(self):
        result = compress_diagnostic_text("boot\nINFO ready\nERROR disk full\nretry\nERROR disk full\nclosed", target_tokens=1)

        self.assertEqual(result["text"], "1: boot\n2: INFO ready\n3: ERROR disk full\n4: retry\n5: ERROR disk full\n6: closed")
        self.assertEqual(result["confidence"], 0.8533)
        self.assertEqual(result["original_lines"], 6)
        self.assertEqual(result["selected_lines"], 6)

    def test_repeated_lines_are_summarized_after_selected_excerpt(self):
        result = compress_diagnostic_text("same\nsame\nsame\nERROR stopped")

        self.assertTrue(result["success"])
        self.assertIn("REPEATED: 3x same", result["text"])

    def test_engine_method_preserves_compressor_behavior(self):
        text = "boot\nERROR stopped"

        self.assertEqual(DeterministicEngine.compress_text(object.__new__(DeterministicEngine), text), compress_diagnostic_text(text))


if __name__ == "__main__":
    unittest.main()
