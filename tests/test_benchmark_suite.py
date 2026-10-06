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


def test_benchmark_runner_supports_non_streaming_runtime(tmp_path: Path) -> None:
    class GenerateOnlyRuntime:
        def generate(self, model, prompt, options=None):
            assert model == "qwen2.5-coder:7b"
            assert prompt == "return 42"
            assert options == {"num_predict": 4, "think": False}
            return {"text": "42"}

    runner = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=GenerateOnlyRuntime(),
    )

    result = runner.run(model="qwen2.5-coder:7b", prompt="return 42", num_tokens=4)

    assert result["success"] is True
    assert result["tokens_generated"] == 1
    assert result["whitespace_token_estimate"] == 1
    assert result["token_count_method"] == "whitespace_token_estimate_not_model_tokenization"


def test_benchmark_runner_does_not_treat_error_response_as_success(tmp_path: Path) -> None:
    class ErrorRuntime:
        def generate(self, model, prompt, options=None):
            return {"error": "HTTP 404: model not found"}

    runner = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=ErrorRuntime(),
    )

    result = runner.run(model="qwen3.5:9b", prompt="Return BENCH_OK", num_tokens=16)

    assert result["success"] is False
    assert result["model"] == "qwen3.5:9b"
    assert "404" in result["error"]
    assert not (tmp_path / "benchmarks.json").exists()


def test_benchmark_runner_reports_insufficient_sample_for_one_token_output(tmp_path: Path) -> None:
    class ShortRuntime:
        def generate(self, model, prompt, options=None):
            return {"response": "OK", "eval_count": 1, "eval_duration": 1_000_000}

    runner = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=ShortRuntime(),
    )

    result = runner.run(model="qwen2.5-coder:7b", prompt="Return OK", num_tokens=16)

    assert result["success"] is True
    assert result["tokens_generated"] == 1
    assert result["measurement_warning"] == "insufficient_output_tokens"
    assert result["hardware_score"] is None


def test_benchmark_runner_rejects_thinking_only_stream(tmp_path: Path) -> None:
    class ThinkingOnlyRuntime:
        def generate_stream(self, model, prompt, options=None):
            assert options == {"num_predict": 16, "think": False}
            yield {"thinking": "internal reasoning without visible answer"}

    runner = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=ThinkingOnlyRuntime(),
    )

    result = runner.run(model="qwen3.5:9b", prompt="Return BENCH_OK", num_tokens=16)

    assert result["success"] is False
    assert result["measurement_warning"] == "thinking_only_output"
    assert not (tmp_path / "benchmarks.json").exists()


def test_benchmark_runner_reports_model_load_duration_from_runtime(tmp_path: Path) -> None:
    class RuntimeWithLoadMetric:
        def generate(self, model, prompt, options=None):
            return {"response": "loaded and ready", "eval_count": 2, "load_duration": 250_000_000}

    runner = HardwareBenchmarkRunner(benchmarks_path=tmp_path / "benchmarks.json", runtime=RuntimeWithLoadMetric())

    result = runner.run(model="qwen2.5-coder:7b", prompt="return OK", num_tokens=2)

    assert result["success"] is True
    assert result["load_duration_ms"] == 250.0


def test_benchmark_runner_reports_model_load_duration_from_stream_metadata(tmp_path: Path) -> None:
    class StreamingRuntimeWithLoadMetric:
        def generate_stream(self, model, prompt, options=None):
            yield {"response": "ready"}
            yield {"done": True, "load_duration": 75_000_000}

    runner = HardwareBenchmarkRunner(benchmarks_path=tmp_path / "benchmarks.json", runtime=StreamingRuntimeWithLoadMetric())

    result = runner.run(model="qwen2.5-coder:7b", prompt="return OK", num_tokens=2)

    assert result["success"] is True
    assert result["load_duration_ms"] == 75.0


def test_stream_ttft_uses_first_visible_chunk_and_backend_token_metrics(tmp_path: Path) -> None:
    class RuntimeWithThinkingAndMetrics:
        def generate_stream(self, model, prompt, options=None):
            yield {"thinking": "hidden warm-up"}
            time.sleep(0.04)
            yield {"response": "visible answer", "eval_count": 5, "eval_duration": 500_000_000}

    runner = HardwareBenchmarkRunner(benchmarks_path=tmp_path / "benchmarks.json", runtime=RuntimeWithThinkingAndMetrics())

    result = runner.run(model="qwen3.5:9b", prompt="return OK", num_tokens=8)

    assert result["success"] is True
    assert result["ttft_ms"] >= 30.0
    assert result["tokens_generated"] == 5
    assert result["token_count_estimated"] is False
    assert result["whitespace_token_estimate"] is None
    assert result["token_count_method"] == "backend_eval_count"
    assert result["tokens_per_second"] == 10.0
