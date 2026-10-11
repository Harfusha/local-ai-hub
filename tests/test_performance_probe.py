from __future__ import annotations

import subprocess

import pytest

import local_ai_hub.performance_probe as performance_probe
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


def test_performance_probe_uses_hidden_windows_process_options(monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(args[0], 0)

    monkeypatch.setattr(performance_probe, "hidden_run_kwargs", lambda: {"creationflags": 123}, raising=False)
    monkeypatch.setattr(performance_probe.subprocess, "run", fake_run)

    result = performance_probe.run_probe("http", ["python", "-V"], iterations=1, warmup=1)

    assert result["success"] is True
    assert len(calls) == 2
    assert all(call["creationflags"] == 123 for call in calls)
