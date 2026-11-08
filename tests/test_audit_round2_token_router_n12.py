from __future__ import annotations

import json
from unittest.mock import MagicMock
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
