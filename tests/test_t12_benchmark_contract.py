from __future__ import annotations

import time
from pathlib import Path

from local_ai_hub.benchmark import HardwareBenchmarkRunner
from tools.benchmark_surfaces import _run_t12_matrix, _t12_scenario_report


def test_t12_case_reports_backend_throughput_and_end_to_end_latency(tmp_path: Path) -> None:
    class Runtime:
        def generate_stream(self, model, prompt, options=None):
            self.options = options
            time.sleep(0.01)
            yield {
                "response": '{"answer":"42"}',
                "load_duration": 5_000_000,
                "prompt_eval_count": 6,
                "eval_count": 9,
                "eval_duration": 2_000_000_000,
            }

        def model_digest(self, model):
            return "a" * 64

        def loaded_model_details(self, *, force_refresh=False):
            del force_refresh
            return [{"name": "qwen2.5-coder:7b", "vram_bytes": 400 * 1024 * 1024}]

    class Scheduler:
        def submit(self, model, tenant, source, execute, **kwargs):
            result = execute()
            result["_lah_scheduler_queue_wait_ms"] = 12.5
            result["admission"] = {
                "queue_age_ms": 12.5,
                "vram_budget_bytes": 1024 * 1024 * 1024,
                "vram_available_bytes": 768 * 1024 * 1024,
                "vram_admission": "admitted",
            }
            return result

    runner = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=Runtime(),
        scheduler=Scheduler(),
        config={"models": {"reasoning": "qwen2.5-coder:7b"}, "_hardware": "test-gpu"},
    )

    result = runner.run_t12_case(
        task="reason",
        model="qwen2.5-coder:7b",
        prompt="Return the expected structured answer.",
        num_tokens=8,
        expected={"answer": "42"},
        evidence_paths=[],
    )

    assert result["success"] is True
    assert result["queue_wait_ms"] == 12.5
    assert result["queue_age_ms"] == 12.5
    assert result["tokens_per_second"] == 4.5
    assert result["end_to_end_latency_ms"] >= result["ttft_ms"]
    assert result["deadline_queue_ms"] == 12.5
    assert result["deadline_model_load_ms"] == 5.0
    assert result["deadline_generation_ms"] == 2000.0
    assert result["deadline_stage"] == "generation"
    assert result["deadline_ms"] > result["end_to_end_latency_ms"]
    assert result["model_digest"] == "a" * 64
    assert result["vram_budget_bytes"] == 1024 * 1024 * 1024
    assert result["vram_available_bytes"] == 768 * 1024 * 1024
    assert result["vram_required_bytes"] == 400 * 1024 * 1024
    assert result["vram_admitted"] == "admitted"
    assert result["structured_json_valid"] is True
    assert result["quality_schema_pass"] is True
    assert result["quality_expected_match"] is True
    assert result["quality_paths_grounded"] is True
    assert runner.runtime.options["format"] == "json"
    assert runner.runtime.options["temperature"] == 0


def test_t12_case_does_not_infer_throughput_without_backend_eval_duration(tmp_path: Path) -> None:
    class Runtime:
        def generate_stream(self, model, prompt, options=None):
            yield {"response": '{"answer":"42"}', "eval_count": 9}

    class Scheduler:
        def submit(self, model, tenant, source, execute, **kwargs):
            return execute()

    runner = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=Runtime(),
        scheduler=Scheduler(),
        config={"models": {"reasoning": "qwen2.5-coder:7b"}},
    )

    result = runner.run_t12_case(
        task="reason",
        model="qwen2.5-coder:7b",
        prompt="Return the expected structured answer.",
        num_tokens=8,
        expected={"answer": "42"},
        evidence_paths=[],
    )

    assert "tokens_per_second" not in result
    assert "deadline_generation_ms" not in result


def test_t12_case_uses_runtime_request_stream_and_final_metrics(tmp_path: Path) -> None:
    class Runtime:
        def request_stream(self, endpoint, payload, on_chunk, timeout=None):
            assert endpoint == "/api/generate"
            assert payload["stream"] is True
            time.sleep(0.01)
            on_chunk('{"answer":"42"}')
            return {
                "response": '{"answer":"42"}',
                "eval_count": 9,
                "eval_duration": 2_000_000_000,
            }

    class Scheduler:
        def submit(self, model, tenant, source, execute, **kwargs):
            return execute()

    runner = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=Runtime(),
        scheduler=Scheduler(),
        config={"models": {"reasoning": "qwen2.5-coder:7b"}},
    )

    result = runner.run_t12_case(
        task="reason",
        model="qwen2.5-coder:7b",
        prompt="Return the expected structured answer.",
        num_tokens=8,
        expected={"answer": "42"},
        evidence_paths=[],
    )

    assert result["success"] is True
    assert result["ttft_ms"] > 0
    assert result["tokens_per_second"] == 4.5
    assert result["deadline_generation_ms"] == 2000.0


def test_t12_scenario_hook_forwards_contract_metrics_for_all_scenarios(tmp_path: Path) -> None:
    fixtures = {
        "scheduler": {
            "queue_age_ms": 25.0,
            "fairness_wait_ms": 10.0,
            "bucket_id": "short-prefill",
            "batch_size": 4,
            "batch_item_count": 4,
            "prefill_tokens": 128,
            "vram_admission": "admitted",
            "vram_budget_bytes": 512 * 1024 * 1024,
            "vram_available_bytes": 256 * 1024 * 1024,
            "vram_required_bytes": 256 * 1024 * 1024,
            "vram_admission_budget_bytes": 256 * 1024 * 1024,
            "vram_incremental_required_bytes": 192 * 1024 * 1024,
            "vram_estimate_source": "measured",
        },
        "batch": {
            "input_item_ids": ["a", "b", "c"],
            "result_item_ids": ["a", "b", "c"],
            "item_statuses": ["success", "failed", "success"],
            "partial_failure_count": 1,
            "max_concurrency": 2,
            "concurrency_limit": 2,
            "failure_probe_item_id": "b",
            "failure_probe_observed": True,
        },
        "deadline": {
            "deadline_ms": 100.0,
            "stages": ["queue", "model_load", "generation"],
            "stage_timings_ms": {"queue": 5.0, "model_load": 20.0, "generation": 40.0},
            "deadline_stage": "generation",
            "completed_within_deadline": True,
            "request_succeeded": True,
        },
        "overload": {
            "overloaded": True, "queue_depth": 4, "queue_admission": "rejected",
            "queued_count": 1, "rejected_count": 1,
        },
        "cancel": {
            "cancel_requested": True,
            "cancelled": True,
            "cleanup_complete": True,
            "cancel_to_stop_ms": 15.0,
        },
        "fallback": {
            "fallback_used": True,
            "fallback_visible": True,
            "source_profile": "reasoning",
            "fallback_profile": "review",
            "quality_floor_pct": 80.0,
            "fallback_quality_pct": 85.0,
        },
    }

    class Scheduler:
        def __init__(self) -> None:
            self.scenario_calls: list[tuple[str, dict[str, object]]] = []

        def submit(self, model, tenant, source, execute, **kwargs):
            return execute()

        def run_benchmark_scenario(self, *, name: str, contract: dict[str, object]):
            self.scenario_calls.append((name, contract))
            return {
                **fixtures[name],
                "receipt_id": f"fixture-{name}",
                "unrequested_payload": "must not escape scenario adapter",
            }

    scheduler = Scheduler()
    runner = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=object(),
        scheduler=scheduler,
    )

    for name, measurements in fixtures.items():
        contract = {
            "scenario": name,
            "required_fields": list(measurements),
            "concurrency_limit": 2,
            "quality_floor_pct": 80.0,
        }
        result = runner.run_benchmark_scenario(name=name, contract=contract)

        assert result == {
            "success": True,
            **measurements,
            "receipt_id": f"fixture-{name}",
        }

    assert [name for name, _ in scheduler.scenario_calls] == list(fixtures)

    fixtures["scheduler"]["vram_required_bytes"] = 300 * 1024 * 1024
    scheduler_contract = {
        "scenario": "scheduler",
        "required_fields": list(fixtures["scheduler"]),
        "concurrency_limit": 2,
        "quality_floor_pct": 80.0,
    }
    over_budget = runner.run_benchmark_scenario(name="scheduler", contract=scheduler_contract)

    assert over_budget["success"] is True
    assert over_budget["vram_required_bytes"] == 300 * 1024 * 1024
    assert over_budget["receipt_id"] == "fixture-scheduler"

    fixtures["scheduler"]["vram_required_bytes"] = 0
    zero_vram = runner.run_benchmark_scenario(name="scheduler", contract=scheduler_contract)

    assert zero_vram["success"] is True
    assert zero_vram["vram_required_bytes"] == 0
    assert zero_vram["receipt_id"] == "fixture-scheduler"

    class AcceptanceRunner:
        config = {"models": {"reasoning": "primary-model", "fast_code": "fallback-model"}}

        def run_benchmark_scenario(self, *, name: str, contract: dict[str, object]):
            if name != "batch":
                return {**fixtures[name], "receipt_id": f"fixture-{name}"}
            scenario_inputs = contract["scenario_inputs"]
            item_ids = [item["id"] for item in scenario_inputs["items"]]
            probe_id = scenario_inputs["failure_probe_item_id"]
            probe_index = item_ids.index(probe_id)
            statuses = ["success"] * len(item_ids)
            statuses[probe_index] = "failed"
            return {
                **fixtures[name],
                "input_item_ids": item_ids,
                "result_item_ids": item_ids,
                "item_statuses": statuses,
                "partial_failure_count": 1,
                "failure_probe_item_id": probe_id,
                "failure_probe_observed": True,
                "receipt_id": f"fixture-{name}",
            }

    for measured_vram in (300 * 1024 * 1024, 0):
        fixtures["scheduler"]["vram_required_bytes"] = measured_vram
        report = _t12_scenario_report(
            AcceptanceRunner(),
            "scheduler",
            concurrency_limit=2,
            quality_floor_pct=80.0,
            live_hardware=True,
        )

        assert report["contract_passed"] is False
        assert report["accepted"] is False
        assert "runner_receipt_id" not in report


def test_t12_scenario_hook_fails_closed_on_partial_metrics_or_missing_receipt(tmp_path: Path) -> None:
    class Scheduler:
        payload: dict[str, object] = {}

        def submit(self, model, tenant, source, execute, **kwargs):
            return execute()

        def run_benchmark_scenario(self, *, name: str, contract: dict[str, object]):
            return self.payload

    scheduler = Scheduler()
    runner = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=object(),
        scheduler=scheduler,
    )
    contract = {
        "scenario": "scheduler",
        "required_fields": ["queue_age_ms", "fairness_wait_ms"],
    }

    for payload in (
        {
            "queue_age_ms": 12.0,
            "receipt_id": "fixture-partial-metrics",
        },
        {
            "queue_age_ms": 12.0,
            "fairness_wait_ms": 8.0,
        },
    ):
        scheduler.payload = payload
        result = runner.run_benchmark_scenario(name="scheduler", contract=contract)
        assert result.get("success") is False
        assert "queue_age_ms" not in result
        assert "fairness_wait_ms" not in result
        assert "receipt_id" not in result


def test_t12_scenario_hook_fails_closed_without_executor(tmp_path: Path) -> None:
    class Scheduler:
        def submit(self, model, tenant, source, execute, **kwargs):
            return execute()

    runner = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=object(),
        scheduler=Scheduler(),
    )

    result = runner.run_benchmark_scenario(
        name="scheduler",
        contract={"scenario": "scheduler", "required_fields": ["queue_age_ms"]},
    )

    assert result == {"success": False, "error_type": "scenario_executor_unavailable"}


def test_t12_scenario_inputs_are_forwarded_and_failed_measurement_has_no_success_receipt() -> None:
    class Runner:
        config = {
            "models": {"reasoning": "primary-model", "fast_code": "fallback-model"},
            "_hardware": {"profile": "balanced"},
        }

        def run_benchmark_scenario(self, *, name: str, contract: dict[str, object]):
            self.contract = contract
            return {
                "success": True,
                "overloaded": False,
                "queue_depth": 4,
                "queue_admission": "rejected",
                "receipt_id": "t12:failed-measurement",
            }

    runner = Runner()
    report = _t12_scenario_report(
        runner,
        "overload",
        concurrency_limit=2,
        quality_floor_pct=80.0,
        live_hardware=True,
    )

    inputs = runner.contract["scenario_inputs"]
    assert inputs["model"] == "primary-model"
    assert inputs["profile"] == "balanced"
    assert inputs["fallback_model"] == "fallback-model"
    assert inputs["fallback_profile"] == "fast_code"
    assert len(inputs["items"]) == 4
    assert report["contract_passed"] is False
    assert "runner_receipt_id" not in report


def test_t12_batch_rejects_all_failed_items_even_when_receipt_exists() -> None:
    class Runner:
        config = {"models": {"reasoning": "primary-model"}}

        def run_benchmark_scenario(self, *, name: str, contract: dict[str, object]):
            del name
            inputs = contract["scenario_inputs"]
            item_ids = [item["id"] for item in inputs["items"]]
            probe_id = inputs["failure_probe_item_id"]
            return {
                "input_item_ids": item_ids,
                "result_item_ids": item_ids,
                "item_statuses": ["failed"] * len(item_ids),
                "partial_failure_count": len(item_ids),
                "max_concurrency": 1,
                "concurrency_limit": 2,
                "failure_probe_item_id": probe_id,
                "failure_probe_observed": True,
                "receipt_id": "t12:all-failed",
            }

    report = _t12_scenario_report(
        Runner(), "batch", concurrency_limit=2, quality_floor_pct=80.0, live_hardware=True,
    )

    assert report["contract_passed"] is False
    assert report["accepted"] is False
    assert "runner_receipt_id" not in report


def test_t12_overload_accepts_observed_queueing_without_requiring_rejection() -> None:
    class Runner:
        config = {"models": {"reasoning": "primary-model"}}

        def run_benchmark_scenario(self, *, name: str, contract: dict[str, object]):
            del name, contract
            return {
                "overloaded": True,
                "queue_depth": 3,
                "queue_admission": "queued",
                "queued_count": 2,
                "rejected_count": 0,
                "receipt_id": "t12:queued",
            }

    report = _t12_scenario_report(
        Runner(), "overload", concurrency_limit=2, quality_floor_pct=80.0, live_hardware=True,
    )

    assert report["contract_passed"] is True
    assert report["accepted"] is True
    assert report["runner_receipt_id"] == "t12:queued"


def test_t12_deadline_requires_timely_success_and_separate_request_outcome() -> None:
    class Runner:
        config = {"models": {"reasoning": "primary-model"}}

        def __init__(self, succeeded: bool) -> None:
            self.succeeded = succeeded

        def run_benchmark_scenario(self, *, name: str, contract: dict[str, object]):
            del name, contract
            return {
                "deadline_ms": 100.0,
                "stages": ["queue", "model_load", "generation"],
                "stage_timings_ms": {"queue": 1.0, "model_load": 2.0, "generation": 3.0},
                "deadline_stage": "generation",
                "completed_within_deadline": True,
                "request_succeeded": self.succeeded,
                "receipt_id": "t12:deadline",
            }

    failed_request = _t12_scenario_report(
        Runner(False), "deadline", concurrency_limit=2, quality_floor_pct=80.0, live_hardware=True,
    )
    successful_request = _t12_scenario_report(
        Runner(True), "deadline", concurrency_limit=2, quality_floor_pct=80.0, live_hardware=True,
    )

    assert failed_request["accepted"] is False
    assert successful_request["accepted"] is True


def test_t12_profile_matrix_uses_runner_timing_and_flat_deadline_metrics() -> None:
    class Runner:
        config = {
            "models": {
                "reasoning": "reason-model",
                "heavy_code": "review-model",
                "fast_code": "fast-model",
            },
            "_hardware": {"profile": "balanced"},
        }

        def run_t12_case(self, *, task: str, model: str, **kwargs: object):
            del kwargs
            routed_profile = {
                "reason": "reasoning",
                "review": "heavy_code",
                "compress": "fast_code",
                "complete": "fast_code",
                "scaffold": "heavy_code",
            }[task]
            return {
                "success": True,
                "model": model,
                "model_digest": "a" * 64,
                "routed_profile": routed_profile,
                "quality_evaluator_id": "model_quality.evaluate_case:t12.v1",
                "quality_score_pct": 100.0,
                "ttft_ms": 4.0,
                "end_to_end_latency_ms": 42.5,
                "tokens_per_second": 20.0,
                "load_duration_ms": 0.0,
                "queue_age_ms": 1.0,
                "queue_wait_ms": 1.0,
                "prefill_tokens": 8,
                "vram_budget_bytes": 1024,
                "vram_required_bytes": 512,
                "deadline_queue_ms": 1.0,
                "deadline_model_load_ms": 0.0,
                "deadline_generation_ms": 20.0,
                "peak_vram_bytes": 700,
                "peak_vram_scope": "device_wide_sampled_during_inference",
                "model_load_event": False,
                "model_reuse_event": True,
                "vram_admitted": "admitted",
                "deadline_ms": 30000.0,
                "deadline_stage": "generation",
                "deadline_exceeded": False,
            }

    result = _run_t12_matrix(
        Runner(), repetitions=1, concurrency_limit=2, quality_floor_pct=80.0, live_hardware=True,
    )

    role = result["task_roles"]["review"]
    sample = role["samples"][0]
    assert sample["end_to_end_latency_ms"] == 42.5
    assert sample["deadline_queue_ms"] == 1.0
    assert sample["deadline_model_load_ms"] == 0.0
    assert sample["deadline_generation_ms"] == 20.0
    assert sample["peak_vram_scope"] == "device_wide_sampled_during_inference"
    assert "fairness_wait_ms_missing" not in role["missing_acceptance"]
    assert "batch_size_missing" not in role["missing_acceptance"]
