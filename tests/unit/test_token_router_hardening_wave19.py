from pathlib import Path
import pytest
from unittest.mock import MagicMock
from local_ai_hub.token_router import LosslessTokenRouter


def test_token_router_route_text_hardening(tmp_path: Path):
    services = MagicMock()
    config = {
        "lossless_router": {"enabled": True},
        "server": {"state_dir": str(tmp_path)},
    }
    router = LosslessTokenRouter(config, services)

    # Non-string text should return error dict rather than crashing on text.splitlines()
    res_none = router.route_text(None, "search query")
    assert not res_none["success"]
    assert res_none["error"] == "text must be a string"

    res_bool = router.route_text(True, "search query")
    assert not res_bool["success"]

    # Boolean query and path are safely sanitized.
    res_sanitized = router.route_text("line 1\nline 2\nline 3", query=True, path=True)
    assert res_sanitized["success"]
    assert res_sanitized["context"]

    # Retired tenant contracts reject instead of shifting into another argument.
    with pytest.raises(TypeError):
        router.route_text("text", "query", "old-tenant")
    with pytest.raises(TypeError):
        router.route_text("text", "query", tenant=None)


def test_token_router_parse_ranges_hardening():
    # Booleans in start/end should be skipped and not coerced to int(True)=1
    json_text = '{"ranges": [{"start": true, "end": 10}, {"start": 5, "end": false}, {"start": 2, "end": 4}]}'
    ranges = LosslessTokenRouter._parse_ranges(json_text, max_line=10, max_ranges=5, context_lines=0)
    assert len(ranges) == 1
    assert ranges[0][0] == 2
    assert ranges[0][1] == 4


def test_token_router_render_bounds_hardening():
    lines = ["a", "b", "c"]
    # Out of bounds ranges should not raise IndexError
    out, evidence = LosslessTokenRouter._render(lines, [(1, 100, 1.0)], path="test.py")
    assert "--- test.py:1-3 ---" in out
    assert len(evidence) == 1
    assert evidence[0]["end_line"] == 3
