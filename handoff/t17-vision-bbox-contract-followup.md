# T17 vision bbox contract follow-up

The vision prompt described `bbox` as `[x, y, width, height]`, while `parse_vision_result()` interprets the values as `[left, top, right, bottom]` and validates them against image dimensions. Updated the prompt to use the parser's edge-coordinate contract and added a focused prompt regression assertion.

Changed files: `src/local_ai_hub/services.py` within `LocalAIServices.vision()` only; `tests/test_vision_service.py` prompt assertion only. `git diff --check` passed for both paths. Targeted tests remain unrun while T02 owns the test slot.

No change touches `/api/context/pack`. Browser integration and live vision grounding acceptance remain open: prior browser UI control was unavailable, and the cached vision model produced an unsupported DOM ID that the parser rejected.
