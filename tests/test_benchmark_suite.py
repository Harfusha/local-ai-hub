from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from local_ai_hub.benchmark import HardwareBenchmarkRunner
from local_ai_hub.scheduler import QueueFullError


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


def test_benchmark_records_verified_model_digest_and_exact_loaded_vram(tmp_path: Path) -> None:
    runtime = MagicMock()
    runtime.generate_stream.side_effect = lambda *_args, **_kwargs: iter(["one ", "two ", "three"])
    runtime.model_digest.return_value = "a" * 64
    runtime.loaded_model_details.return_value = [
        {"name": "selected-model", "vram_bytes": 1234},
        {"name": "other-model", "vram_bytes": 9876},
    ]
    benchmarks_file = tmp_path / "benchmarks.json"
    runner = HardwareBenchmarkRunner(benchmarks_path=benchmarks_file, runtime=runtime)

    result = runner.run(model="selected-model", prompt="prompt", num_tokens=3)

    assert result["model_digest"] == "a" * 64
    assert result["model_digest_status"] == "verified_installed"
    assert result["loaded_model_vram_bytes"] == 1234
    assert result["loaded_model_vram_status"] == "observed_loaded_model"
    saved = json.loads(benchmarks_file.read_text(encoding="utf-8"))
    assert saved[0]["model_digest"] == "a" * 64
    assert saved[0]["loaded_model_vram_bytes"] == 1234


def test_benchmark_marks_model_evidence_unavailable_without_exact_runtime_data(tmp_path: Path) -> None:
    runtime = MagicMock()
    runtime.generate_stream.side_effect = lambda *_args, **_kwargs: iter(["one ", "two ", "three"])
    runtime.model_digest.return_value = "invalid-digest"
    runtime.loaded_model_details.return_value = [
        {"name": "different-model", "vram_bytes": 1234},
        {"name": "selected-model", "vram_bytes": 0},
    ]
    runner = HardwareBenchmarkRunner(benchmarks_path=tmp_path / "benchmarks.json", runtime=runtime)

    result = runner.run(model="selected-model", prompt="prompt", num_tokens=3)

    assert result["model_digest"] is None
    assert result["model_digest_status"] == "unavailable"
    assert result["loaded_model_vram_bytes"] is None
    assert result["loaded_model_vram_status"] == "unavailable"


def test_benchmark_measures_ttft_after_queue_and_vram_after_scheduler_preparation(tmp_path: Path) -> None:
    class Scheduler:
        inside_execution = False

        def submit(self, _model, *, execute, **_kwargs):
            time.sleep(0.1)
            self.inside_execution = True
            try:
                result = execute()
            finally:
                self.inside_execution = False
            return {**result, "_lah_scheduler_queue_wait_ms": 100.0}

    scheduler = Scheduler()

    class Runtime:
        def loaded_model_details(self, *, force_refresh=False):
            if scheduler.inside_execution:
                return [{"name": "selected-model", "vram_bytes": 4321}]
            return []

        def generate_stream(self, *_args, **_kwargs):
            time.sleep(0.02)
            yield {"response": "one two", "eval_count": 2, "eval_duration": 20_000_000}

    runner = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=Runtime(),
        scheduler=scheduler,
    )

    result = runner.run(model="selected-model", prompt="prompt", num_tokens=2)

    assert result["queue_wait_ms"] == 100.0
    assert result["ttft_ms"] < result["queue_wait_ms"]
    assert result["loaded_model_vram_bytes"] == 4321
    assert result["loaded_model_vram_status"] == "observed_loaded_model"


def test_benchmark_uses_callback_streaming_runtime_for_true_ttft(tmp_path: Path) -> None:
    class Scheduler:
        inside_execution = False

        def submit(self, _model, *, execute, **_kwargs):
            time.sleep(0.1)
            self.inside_execution = True
            try:
                result = execute()
            finally:
                self.inside_execution = False
            return {**result, "_lah_scheduler_queue_wait_ms": 100.0}

    scheduler = Scheduler()

    class Runtime:
        def loaded_model_details(self, *, force_refresh=False):
            if scheduler.inside_execution:
                return [{"name": "selected-model", "vram_bytes": 4321}]
            return []

        def request_stream(self, endpoint, payload, on_chunk, timeout=None):
            assert endpoint == "/api/generate"
            assert payload["stream"] is True
            assert payload["model"] == "selected-model"
            time.sleep(0.02)
            on_chunk("one two")
            return {"eval_count": 2, "eval_duration": 20_000_000}

    runner = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=Runtime(),
        scheduler=scheduler,
    )

    result = runner.run(model="selected-model", prompt="prompt", num_tokens=2)

    assert result["streaming"] is True
    assert result["queue_wait_ms"] == 100.0
    assert result["ttft_ms"] < result["queue_wait_ms"]
    assert result["tokens_generated"] == 2
    assert result["loaded_model_vram_bytes"] == 4321


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
    assert result["streaming"] is False
    assert result["ttft_ms"] is None
    assert result["latency_basis"] == "full_call"
    assert result["call_latency_ms"] > 0
    latest = runner.get_latest_summary()
    assert latest["ttft_ms"] is None
    assert latest["call_latency_ms"] == result["call_latency_ms"]
    assert latest["latency_basis"] == "full_call"
    runner.benchmarks_path.write_text(
        json.dumps([{"model": "legacy", "streaming": False, "ttft_ms": 12.5}]),
        encoding="utf-8",
    )
    legacy_latest = runner.get_latest_summary()
    assert legacy_latest["ttft_ms"] is None
    assert legacy_latest["call_latency_ms"] == 12.5
    assert legacy_latest["latency_basis"] == "full_call"
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


def test_hardware_benchmark_uses_scheduler_for_model_preparation(tmp_path: Path) -> None:
    class Runtime:
        def generate_stream(self, model, prompt, options=None):
            assert model == "candidate"
            assert options == {"num_predict": 2, "think": False}
            yield {"response": "ok", "eval_count": 2, "eval_duration": 1_000_000}

    class Scheduler:
        def __init__(self):
            self.calls = []

        def submit(self, model, *, source, execute, priority, wait_timeout):
            self.calls.append((model, source, priority, wait_timeout))
            result = execute()
            result["_lah_scheduler_queue_wait_ms"] = 12.5
            return result

    scheduler = Scheduler()
    runner = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=Runtime(),
        scheduler=scheduler,
        config={"server": {"request_timeout_seconds": 8}},
    )

    result = runner.run(model="candidate", prompt="measure", num_tokens=2)

    assert result["success"] is True
    assert scheduler.calls == [("candidate", "benchmark", 2, 8.0)]
    assert result["queue_wait_ms"] == 12.5


def test_managed_mixed_backend_benchmark_fails_closed_without_scheduler(tmp_path: Path) -> None:
    class Runtime:
        def generate(self, *_args, **_kwargs):
            raise AssertionError("benchmark must not bypass managed model preparation")

    benchmarks_file = tmp_path / "benchmarks.json"
    runner = HardwareBenchmarkRunner(
        benchmarks_path=benchmarks_file,
        runtime=Runtime(),
        config={"llama_cpp": {"managed_with_ollama": True}},
    )

    result = runner.run(model="candidate", prompt="measure", num_tokens=2)

    assert result["success"] is False
    assert "Scheduler required" in result["error"]
    assert not benchmarks_file.exists()


def test_hardware_benchmark_preserves_scheduler_admission_failure(tmp_path: Path) -> None:
    class Runtime:
        def generate(self, *_args, **_kwargs):
            raise AssertionError("rejected benchmark must not reach inference")

    class Scheduler:
        def submit(self, *_args, **_kwargs):
            return {"success": False, "error": "model preparation required",
                    "error_code": "model_preparation_required", "operation_not_started": True}

    benchmarks_file = tmp_path / "benchmarks.json"
    runner = HardwareBenchmarkRunner(
        benchmarks_path=benchmarks_file,
        runtime=Runtime(),
        scheduler=Scheduler(),
    )

    result = runner.run(model="candidate", prompt="measure", num_tokens=2)

    assert result["success"] is False
    assert result["error_code"] == "model_preparation_required"
    assert result["operation_not_started"] is True
    assert not benchmarks_file.exists()


def test_hardware_benchmark_preserves_scheduler_queue_rejection_reason(tmp_path: Path) -> None:
    class Runtime:
        def generate(self, *_args, **_kwargs):
            raise AssertionError("rejected benchmark must not reach inference")

    class Scheduler:
        def submit(self, *_args, **_kwargs):
            raise QueueFullError(
                "insufficient VRAM for model admission",
                admission={
                    "state": "rejected",
                    "reason": "vram_budget",
                    "vram_admission": "rejected",
                    "retryable": False,
                },
                retryable=False,
            )

    benchmarks_file = tmp_path / "benchmarks.json"
    runner = HardwareBenchmarkRunner(
        benchmarks_path=benchmarks_file,
        runtime=Runtime(),
        scheduler=Scheduler(),
    )

    result = runner.run(model="candidate", prompt="measure", num_tokens=2)

    assert result["success"] is False
    assert result["error"] == "insufficient VRAM for model admission"
    assert result["error_code"] == "vram_budget"
    assert result["admission_state"] == "rejected"
    assert result["retryable"] is False
    assert result["terminal"] is True
    assert result["vram_admission"] == "rejected"
    assert not benchmarks_file.exists()


def test_hardware_benchmark_reports_peak_device_vram_during_generation(tmp_path: Path) -> None:
    class Balancer:
        def __init__(self):
            self.samples = 0
            self.sampled_twice = threading.Event()

        def sample_vram(self):
            self.samples += 1
            if self.samples >= 3:
                self.sampled_twice.set()
            used = {1: 80, 2: 100, 3: 110}.get(self.samples, 90)
            return {"vram_used_mb": used, "vram_total_mb": 16303}

    class Runtime:
        def generate_stream(self, model, prompt, options=None):
            assert balancer.sampled_twice.wait(1.0)
            yield {"response": "ok", "eval_count": 2, "eval_duration": 1_000_000}

    balancer = Balancer()
    runner = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=Runtime(),
        vram_balancer=balancer,
    )

    result = runner.run(model="candidate", prompt="measure", num_tokens=2)

    assert result["success"] is True
    assert result["peak_vram_bytes"] == 110 * 1024 * 1024
    assert result["peak_vram_scope"] == "device_wide_sampled_during_inference"


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


def test_run_t12_case_reports_live_metrics_and_persists_no_prompt_or_output(tmp_path: Path) -> None:
    prompt_secret = "private t12 prompt marker"
    generated_json = '{"answer":"42"}'

    class Runtime:
        def generate_stream(self, model, prompt, options=None):
            assert model == "qwen2.5-coder:7b"
            assert prompt == prompt_secret
            assert options["num_predict"] == 8
            time.sleep(0.3)
            yield {
                "response": generated_json,
                "load_duration": 200_000_000,
                "prompt_eval_count": 6,
            }

    class Scheduler:
        def submit(self, model, *, source, execute, **kwargs):
            result = execute()
            result["_lah_scheduler_queue_wait_ms"] = 12.5
            return result

    class VramSampler:
        samples = iter(({"available": True, "vram_used_mb": 100.0}, {"available": True, "vram_used_mb": 110.0}))

        def sample_vram(self):
            return next(self.samples)

    runner = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=Runtime(),
        scheduler=Scheduler(),
        vram_balancer=VramSampler(),
        config={"models": {"reasoning": "qwen2.5-coder:7b"}, "_hardware": "test-gpu"},
    )

    result = runner.run_t12_case(
        task="reason",
        model="qwen2.5-coder:7b",
        prompt=prompt_secret,
        num_tokens=8,
        expected={"answer": "42"},
        evidence_paths=["docs/source.md"],
    )

    assert result["success"] is True
    assert result["queue_wait_ms"] == 12.5
    assert result["ttft_ms"] >= 0.0
    assert result["load_duration_ms"] == 200.0
    assert result["model_load_event"] is True
    assert result["model_reuse_event"] is False
    assert result["prefill_tokens"] == 6
    assert result["peak_vram_bytes"] == 110 * 1024 * 1024
    assert result["peak_vram_scope"] == "device_wide_sampled_during_inference"
    assert result["quality_score_pct"] == 100.0
    assert result["quality_evaluator_id"] == "model_quality.evaluate_case:t12.v1"
    assert result["routed_profile"] == "reasoning"
    assert "output_text" not in result

    persisted = (tmp_path / "benchmarks.json").read_text(encoding="utf-8")
    assert prompt_secret not in persisted
    assert generated_json not in persisted


def test_run_t12_case_omits_unobserved_live_metrics(tmp_path: Path) -> None:
    class Runtime:
        def generate(self, model, prompt, options=None):
            return {"response": '{"answer":"42"}'}

    class Scheduler:
        def submit(self, model, *, source, execute, **kwargs):
            return execute()

    runner = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=Runtime(),
        scheduler=Scheduler(),
    )

    result = runner.run_t12_case(
        task="reason",
        model="qwen2.5-coder:7b",
        prompt="Return structured JSON.",
        num_tokens=8,
        expected={"answer": "42"},
        evidence_paths=[],
    )

    assert result["success"] is True
    assert result["quality_score_pct"] == 100.0
    assert "queue_wait_ms" not in result
    assert "ttft_ms" not in result
    assert "load_duration_ms" not in result
    assert "model_load_event" not in result
    assert "model_reuse_event" not in result
    assert "prefill_tokens" not in result
    assert "peak_vram_bytes" not in result


def test_run_t12_case_reports_model_reuse_only_from_zero_backend_load(tmp_path: Path) -> None:
    class Runtime:
        def generate(self, model, prompt, options=None):
            return {"response": '{"answer":"42"}', "load_duration": 0}

    class Scheduler:
        def submit(self, model, *, source, execute, **kwargs):
            return execute()

    runner = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=Runtime(),
        scheduler=Scheduler(),
        config={"models": {"fast_code": "qwen2.5-coder:1.5b"}},
    )

    result = runner.run_t12_case(
        task="compress",
        model="qwen2.5-coder:1.5b",
        prompt="Return structured JSON.",
        num_tokens=8,
        expected={"answer": "42"},
        evidence_paths=[],
    )

    assert result["load_duration_ms"] == 0.0
    assert result["model_load_event"] is False
    assert result["model_reuse_event"] is True
    assert result["routed_profile"] == "fast_code"


pytestmark = pytest.mark.slow
