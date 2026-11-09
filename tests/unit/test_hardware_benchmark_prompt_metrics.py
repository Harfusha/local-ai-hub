import json
import pytest

from local_ai_hub.benchmark import HardwareBenchmarkRunner


def test_hardware_benchmark_records_backend_prompt_count_and_prefill_rate(tmp_path):
    class Runtime:
        def generate_stream(self, model, prompt, options=None):
            yield {
                "response": "done",
                "prompt_eval_count": 8192,
                "prompt_eval_duration": 250_000_000,
                "eval_count": 2,
                "eval_duration": 100_000_000,
            }

        def model_digest(self, model):
            return "a" * 64

    benchmarks_path = tmp_path / "benchmarks.json"
    runner = HardwareBenchmarkRunner(benchmarks_path=benchmarks_path, runtime=Runtime())

    result = runner.run(model="qwen3.5:9b-nvfp4", prompt="long prompt", num_tokens=8)

    assert result["prompt_eval_count"] == 8192
    assert result["prompt_eval_duration_ms"] == 250.0
    assert result["prefill_tokens_per_second"] == 32768.0
    assert json.loads(benchmarks_path.read_text(encoding="utf-8"))[0]["prompt_eval_count"] == 8192


def test_hardware_benchmark_records_prompt_metrics_from_request_stream_result(tmp_path):
    class Runtime:
        def request_stream(self, endpoint, payload, on_chunk, timeout=None):
            on_chunk("done")
            return {
                "response": "done",
                "prompt_eval_count": 8192,
                "prompt_eval_duration": 250_000_000,
                "eval_count": 2,
                "eval_duration": 100_000_000,
            }

        def model_digest(self, model):
            return "a" * 64

    runner = HardwareBenchmarkRunner(benchmarks_path=tmp_path / "benchmarks.json", runtime=Runtime())

    result = runner.run(model="qwen3.5:9b-nvfp4", prompt="long prompt", num_tokens=8)

    assert result["prompt_eval_count"] == 8192
    assert result["prompt_eval_duration_ms"] == 250.0
    assert result["prefill_tokens_per_second"] == 32768.0


def test_hardware_benchmark_preserves_oom_context_recovery_metadata(tmp_path):
    recovery = {
        "original_num_ctx": 8192,
        "effective_num_ctx": 4096,
        "input_truncated": False,
        "device_changed": False,
        "reason": "oom_context_halved",
    }

    class Runtime:
        def request_stream(self, endpoint, payload, on_chunk, timeout=None):
            on_chunk("done")
            return {
                "response": "done",
                "prompt_eval_count": 4098,
                "prompt_eval_duration": 250_000_000,
                "eval_count": 2,
                "eval_duration": 100_000_000,
                "context_recovery": recovery,
            }

        def model_digest(self, model):
            return "a" * 64

    class VRAMBalancer:
        def sample_vram(self):
            return {"available": True, "dynamic_context_tokens": 8192}

    benchmarks_path = tmp_path / "benchmarks.json"
    runner = HardwareBenchmarkRunner(
        benchmarks_path=benchmarks_path,
        runtime=Runtime(),
        vram_balancer=VRAMBalancer(),
    )

    result = runner.run(
        model="qwen2.5-coder:3b", prompt="long prompt", num_tokens=3, context_tokens=8192,
    )

    assert result["success"] is True
    assert result["requested_context_tokens"] == 8192
    assert result["context_recovery"] == recovery
    saved = json.loads(benchmarks_path.read_text(encoding="utf-8"))[0]
    assert saved["context_recovery"] == recovery


def test_hardware_benchmark_preserves_context_recovery_on_empty_output(tmp_path):
    recovery = {
        "original_num_ctx": 8192,
        "effective_num_ctx": 4096,
        "input_truncated": False,
        "device_changed": False,
        "reason": "oom_context_halved",
    }

    class Runtime:
        def request_stream(self, endpoint, payload, on_chunk, timeout=None):
            return {"context_recovery": recovery, "prompt_eval_count": 4098}

    class VRAMBalancer:
        def sample_vram(self):
            return {"available": True, "dynamic_context_tokens": 8192}

    result = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=Runtime(),
        vram_balancer=VRAMBalancer(),
    ).run(model="qwen2.5-coder:3b", prompt="long prompt", num_tokens=3, context_tokens=8192)

    assert result["success"] is False
    assert result["error"] == "benchmark produced no visible output"
    assert result["context_recovery"] == recovery


def test_hardware_benchmark_records_serving_backend(tmp_path):
    class Runtime:
        def request_stream(self, endpoint, payload, on_chunk, timeout=None):
            on_chunk("done")
            return {"response": "done", "_lah_provider": "llama.cpp-cuda"}

    result = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json", runtime=Runtime(),
    ).run(model="qwen3.5:9b-nvfp4", prompt="short prompt", num_tokens=3)

    assert result["backend_provider"] == "llama.cpp-cuda"


def test_hardware_benchmark_records_loaded_model_context(tmp_path):
    class Runtime:
        def request_stream(self, endpoint, payload, on_chunk, timeout=None):
            on_chunk("done")
            return {"response": "done"}

        def loaded_model_details(self, **_kwargs):
            return [{"name": "qwen2.5-coder:3b", "context_length": 4096, "vram_bytes": 1234}]

    result = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json", runtime=Runtime(),
    ).run(model="qwen2.5-coder:3b", prompt="short prompt", num_tokens=3)

    assert result["loaded_model_context_tokens"] == 4096


def test_hardware_benchmark_forwards_explicit_context_window(tmp_path):
    class Runtime:
        def request_stream(self, endpoint, payload, on_chunk, timeout=None):
            assert endpoint == "/api/generate"
            on_chunk("ok")
            return {
                "response": "ok",
                "prompt_eval_count": 32760,
                "prompt_eval_duration": 1_000_000_000,
                "eval_count": 1,
                "eval_duration": 100_000_000,
            }

        def model_digest(self, model):
            return "a" * 64

    captured = {}

    class CapturingRuntime(Runtime):
        def request_stream(self, endpoint, payload, on_chunk, timeout=None):
            captured.update(payload)
            return super().request_stream(endpoint, payload, on_chunk, timeout)

    class VRAMBalancer:
        def sample_vram(self):
            return {"available": True, "dynamic_context_tokens": 32768}

    runner = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=CapturingRuntime(),
        vram_balancer=VRAMBalancer(),
    )

    result = runner.run(
        model="qwen3.5:9b-nvfp4", prompt="long prompt", num_tokens=3, context_tokens=32768,
    )

    assert result["requested_context_tokens"] == 32768
    assert result["prompt_eval_count"] == 32760
    assert captured["options"]["num_ctx"] == 32768


def test_hardware_benchmark_does_not_qualify_context_above_observed_runner(tmp_path):
    class Runtime:
        def request_stream(self, endpoint, payload, on_chunk, timeout=None):
            on_chunk("ok")
            return {"response": "ok", "prompt_eval_count": 31029}

        def loaded_model_details(self, **_kwargs):
            return [{"name": "qwen3.5:9b-nvfp4", "context_length": 8192, "vram_bytes": 1234}]

    class VRAMBalancer:
        def sample_vram(self):
            return {"available": True, "dynamic_context_tokens": 32768}

    result = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=Runtime(),
        vram_balancer=VRAMBalancer(),
    ).run(model="qwen3.5:9b-nvfp4", prompt="long prompt", num_tokens=3, context_tokens=32768)

    assert result["success"] is True
    assert result["loaded_model_context_tokens"] == 8192
    assert result["context_qualification_status"] == "below_requested"
    assert result["context_qualified"] is False


def test_hardware_benchmark_marks_explicit_context_unknown_without_runner_observation(tmp_path):
    class Runtime:
        def request_stream(self, endpoint, payload, on_chunk, timeout=None):
            on_chunk("ok")
            return {"response": "ok"}

    class VRAMBalancer:
        def sample_vram(self):
            return {"available": True, "dynamic_context_tokens": 8192}

    result = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=Runtime(),
        vram_balancer=VRAMBalancer(),
    ).run(model="qwen2.5-coder:3b", prompt="short prompt", num_tokens=3, context_tokens=8192)

    assert result["context_qualification_status"] == "unknown"
    assert result["context_qualified"] is False


def test_hardware_benchmark_qualifies_context_from_post_request_runner(tmp_path):
    class Runtime:
        context_length = 8192

        def request_stream(self, endpoint, payload, on_chunk, timeout=None):
            self.context_length = payload["options"]["num_ctx"]
            on_chunk("ok")
            return {"response": "ok"}

        def loaded_model_details(self, **_kwargs):
            return [{"name": "qwen3.5:9b-nvfp4", "context_length": self.context_length, "vram_bytes": 1234}]

    class VRAMBalancer:
        def sample_vram(self):
            return {"available": True, "dynamic_context_tokens": 32768}

    result = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=Runtime(),
        vram_balancer=VRAMBalancer(),
    ).run(model="qwen3.5:9b-nvfp4", prompt="long prompt", num_tokens=3, context_tokens=32768)

    assert result["loaded_model_context_tokens"] == 32768
    assert result["context_qualification_status"] == "verified"
    assert result["context_qualified"] is True


def test_hardware_benchmark_does_not_reuse_pre_request_context_when_runner_disappears(tmp_path):
    class Runtime:
        call_count = 0

        def request_stream(self, endpoint, payload, on_chunk, timeout=None):
            on_chunk("ok")
            return {"response": "ok"}

        def loaded_model_details(self, **_kwargs):
            self.call_count += 1
            if self.call_count == 1:
                return [{"name": "qwen2.5-coder:3b", "context_length": 16384, "vram_bytes": 1234}]
            return []

    class VRAMBalancer:
        def sample_vram(self):
            return {"available": True, "dynamic_context_tokens": 8192}

    result = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=Runtime(),
        vram_balancer=VRAMBalancer(),
    ).run(model="qwen2.5-coder:3b", prompt="short prompt", num_tokens=3, context_tokens=8192)

    assert result.get("loaded_model_context_tokens") is None
    assert result["context_qualification_status"] == "unknown"
    assert result["context_qualified"] is False


def test_hardware_benchmark_rejects_context_above_current_vram_budget(tmp_path):
    class Runtime:
        called = False

        def request_stream(self, endpoint, payload, on_chunk, timeout=None):
            self.called = True
            raise AssertionError("context above current budget must reject before inference")

    class VRAMBalancer:
        def sample_vram(self):
            return {"available": True, "dynamic_context_tokens": 16384}

    runtime = Runtime()
    result = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=runtime,
        vram_balancer=VRAMBalancer(),
    ).run(model="qwen3.5:9b-nvfp4", prompt="long prompt", context_tokens=32768)

    assert result["success"] is False
    assert result["error"] == "context_tokens exceeds current dynamic VRAM context budget"
    assert runtime.called is False


def test_hardware_benchmark_requires_live_vram_budget_for_explicit_context(tmp_path):
    class Runtime:
        called = False

        def request_stream(self, endpoint, payload, on_chunk, timeout=None):
            self.called = True
            raise AssertionError("explicit context requires VRAM budget evidence")

    runtime = Runtime()
    result = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json", runtime=runtime,
    ).run(model="qwen3.5:9b-nvfp4", prompt="long prompt", context_tokens=8192)

    assert result["success"] is False
    assert result["error"] == "current dynamic VRAM context budget unavailable"
    assert runtime.called is False


@pytest.mark.parametrize("context_tokens", [True, 4095, 32769, "32768"])
def test_hardware_benchmark_rejects_invalid_context_window(tmp_path, context_tokens):
    class Runtime:
        called = False

        def request_stream(self, endpoint, payload, on_chunk, timeout=None):
            self.called = True
            raise AssertionError("invalid context must reject before inference")

    runtime = Runtime()
    result = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json", runtime=runtime,
    ).run(model="qwen3.5:9b-nvfp4", prompt="long prompt", context_tokens=context_tokens)

    assert result["success"] is False
    assert result["error"] == "context_tokens must be an integer between 4096 and 32768"
    assert runtime.called is False
