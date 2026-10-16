from __future__ import annotations

import math
from pathlib import Path
import pytest

from local_ai_hub import token_economy
from local_ai_hub.token_economy import (
    strip_ansi,
    count_tokens,
    filter_and_print_trimmed,
    is_allowed_trim_command,
)
from local_ai_hub.token_router import LosslessTokenRouter


def test_token_economy_edge_cases(capsys: pytest.CaptureFixture):
    # Non-string input to strip_ansi
    assert strip_ansi(None) == ""  # type: ignore

    # Non-string input to count_tokens
    with pytest.raises(TypeError):
        count_tokens(None)  # type: ignore

    # filter_and_print_trimmed with NaN / Inf / bool max_lines
    lines = [f"line {i}" for i in range(10)]
    for limit in (float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            filter_and_print_trimmed(lines, max_lines=limit)
    filter_and_print_trimmed(lines, max_lines=4)
    out, _ = capsys.readouterr()
    assert "line 0" in out

    # Helper function is_allowed_trim_command
    assert is_allowed_trim_command("rg") is True
    assert is_allowed_trim_command("fd") is True
    assert is_allowed_trim_command("tokcount") is True
    assert is_allowed_trim_command("repo-map") is True
    assert is_allowed_trim_command("rm") is False
    assert is_allowed_trim_command("sh") is False
    assert is_allowed_trim_command(None) is False  # type: ignore


def test_lossless_token_router_edge_cases(tmp_path: Path):
    config = {
        "server": {"state_dir": str(tmp_path)},
        "lossless_router": {
            "max_ranges": float("nan"),
            "context_lines": float("inf"),
            "threshold_tokens": True,
            "deterministic_skip_score": float("nan"),
            "max_output_tokens": float("inf"),
        },
    }
    router = LosslessTokenRouter(config, services=None)
    assert router.is_enabled() is True
    stats = router.stats()
    assert stats["hits"] == 0
    assert stats["misses"] == 0

    # Cache clear
    router.cache_clear()

    # None or invalid query to _terms
    assert router._terms(None) == []  # type: ignore
    assert router._terms("") == []

    # _infer_mode with None
    assert router._infer_mode("", None) == "heavy_code"
    assert router._infer_mode("Traceback (most recent call last):", None) == "error_log"

    # _deterministic_ranges with empty lines
    ranges = router._deterministic_ranges([], "query", "heavy_code")
    assert ranges == [(1, 0, 0.0)]
