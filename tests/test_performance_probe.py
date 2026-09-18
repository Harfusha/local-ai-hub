from __future__ import annotations

import pytest

from local_ai_hub.performance_probe import SUPPORTED_STAGES, build_profiler_command, percentile, validate_stage


def test_performance_probe_accepts_all_requested_stages():
    assert {"preprocess", "index", "rag", "mcp", "http"}.issubset(SUPPORTED_STAGES)
    for stage in SUPPORTED_STAGES:
        assert validate_stage(stage) == stage


def test_performance_probe_rejects_unknown_stage():
    with pytest.raises(ValueError, match="unknown performance stage"):
        validate_stage("ollama")


def test_profiler_command_is_explicit_and_bounded():
    command = build_profiler_command("py-spy", ["python", "-m", "pytest", "-q"])

    assert command[:3] == ["py-spy", "record", "--subprocesses"]
    assert command[-4:] == ["python", "-m", "pytest", "-q"]
    assert percentile([10.0, 20.0, 30.0, 40.0], 95) == 38.5
