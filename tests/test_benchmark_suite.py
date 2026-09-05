from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from local_ai_hub.benchmark import HardwareBenchmarkRunner


def test_benchmark_runner_metrics_and_persistence(tmp_path: Path) -> None:
    benchmarks_file = tmp_path / "benchmarks.json"

    # Mock runtime that simulates token streaming
    mock_runtime = MagicMock()

    def fake_stream(model, prompt, options=None):
        time.sleep(0.05)  # Simulate 50ms TTFT
        yield "token1 "
        time.sleep(0.01)
        yield "token2 "
        time.sleep(0.01)
        yield "token3 "

    mock_runtime.generate_stream.side_effect = fake_stream

    # Mock VRAM balancer
    mock_balancer = MagicMock()
    mock_balancer.sample_vram.return_value = {
        "vram_used_mb": 4096,
        "vram_total_mb": 8192,
        "utilization_pct": 50.0,
    }

    runner = HardwareBenchmarkRunner(
        benchmarks_path=benchmarks_file,
        runtime=mock_runtime,
        vram_balancer=mock_balancer,
    )

    res = runner.run(model="qwen2.5-coder:7b", prompt="def add(a, b):", num_tokens=3)
    assert res["success"] is True
    assert res["ttft_ms"] >= 40.0
    assert res["tokens_per_second"] > 0
    assert "hardware_score" in res
    assert res["model"] == "qwen2.5-coder:7b"

    # Verify persistence
    assert benchmarks_file.exists()
    saved = json.loads(benchmarks_file.read_text(encoding="utf-8"))
    assert len(saved) == 1
    assert saved[0]["model"] == "qwen2.5-coder:7b"

    # Summary
    summary = runner.get_latest_summary()
    assert summary["available"] is True
    assert summary["model"] == "qwen2.5-coder:7b"
    assert summary["tokens_per_second"] > 0


def test_benchmark_runner_handles_offline_runtime(tmp_path: Path) -> None:
    benchmarks_file = tmp_path / "benchmarks.json"
    mock_runtime = MagicMock()
    mock_runtime.generate_stream.side_effect = ConnectionError("Ollama offline")

    runner = HardwareBenchmarkRunner(
        benchmarks_path=benchmarks_file,
        runtime=mock_runtime,
    )

    res = runner.run(model="qwen2.5-coder:7b")
    assert res["success"] is False
    assert "Ollama offline" in res["error"]
