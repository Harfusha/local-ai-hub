from __future__ import annotations

import json
from unittest.mock import MagicMock
import pytest
from local_ai_hub.token_router import LosslessTokenRouter


def test_n12_token_router_caps_huge_llm_range():
    config = {
        "lossless_router": {
            "enabled": True,
            "max_output_lines": 30,
            "threshold_tokens": 10,
        },
        "models": {"fast_code": "test-fast"},
    }
    services = MagicMock()
    # Mock LLM returning an enormous range 1 to 10000
    services._generate.return_value = {
        "success": True,
        "text": json.dumps({"ranges": [{"start": 1, "end": 10000, "score": 1.0}]}),
    }

    router = LosslessTokenRouter(config=config, services=services)
    
    # 500 lines of text
    lines = [f"line {i}: content payload" for i in range(1, 501)]
    text = "\n".join(lines)

    result = router.route_text(text, "content", path="test.py", force_local=True)
    assert result["success"] is True
    assert result["local_selector_used"] is True

    # Count rendered content lines (excluding header ---)
    context_lines = [l for l in result["context"].splitlines() if not l.startswith("---")]
    assert len(context_lines) <= 30, f"Rendered lines {len(context_lines)} exceeded max_output_lines 30"


def test_n12_token_router_merges_overlapping_llm_ranges():
    ranges = [(10, 25, 0.8), (20, 35, 0.9), (40, 50, 0.5)]
    normalized = LosslessTokenRouter._normalize_ranges(ranges, max_output_lines=100, max_line=100)
    assert len(normalized) == 2
    # First range merged 10..35
    assert normalized[0][0] == 10
    assert normalized[0][1] == 35
    assert normalized[0][2] == 0.9
    # Second range 40..50
    assert normalized[1][0] == 40
    assert normalized[1][1] == 50


@pytest.mark.parametrize("score", ["high", None, float("nan"), float("inf"), -0.01, 1.01])
def test_n01_token_router_rejects_invalid_llm_scores(score):
    response = json.dumps({"ranges": [{"start": 2, "end": 4, "score": score}]})
    parsed = LosslessTokenRouter._parse_ranges(response, max_line=10, max_ranges=8, context_lines=0)
    assert parsed == []

    services = MagicMock()
    services._generate.return_value = {"success": True, "text": response}
    router = LosslessTokenRouter(
        config={"lossless_router": {"enabled": True}, "models": {"fast_code": "test-fast"}},
        services=services,
    )
    unique_path = f"test-{type(score).__name__}-{str(score)}.py"
    result = router.route_text("alpha payload\nbeta payload\ngamma", "payload", path=unique_path, force_local=True)

    assert result["success"] is True
    assert result["local_selector_used"] is False
    assert router.fallbacks == 1
