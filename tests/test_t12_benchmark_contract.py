from __future__ import annotations

import re
import time
from pathlib import Path

from local_ai_hub.benchmark import HardwareBenchmarkRunner
from local_ai_hub.scheduler import QueueFullError
from tools.benchmark_surfaces import _T12_PROFILE_CORPUS, _run_t12_matrix, _t12_scenario_report


def test_t12_quality_prompts_do_not_assign_expected_oracle_values() -> None:
    assert set(_T12_PROFILE_CORPUS) == {"reason", "review", "compress", "complete", "scaffold"}
    assert all(len(cases) == 1 for cases in _T12_PROFILE_CORPUS.values())

    for role, cases in _T12_PROFILE_CORPUS.items():
        for case in cases:
            prompt = str(case["prompt"])
            for expected_key in case["expected"]:
                assignment = rf"(?<![\w]){re.escape(expected_key)}\s*="
                assert re.search(assignment, prompt) is None, f"{role} prompt reveals {expected_key}"


def test_t12_case_reports_backend_throughput_and_end_to_end_latency(tmp_path: Path) -> None:
    class Runtime:
        load_duration = 5_000_000

        def generate_stream(self, model, prompt, options=None):
            self.options = options
            time.sleep(0.01)
            yield {
                "response": '{"answer":"42"}',
                "load_duration": self.load_duration,
                "prompt_eval_count": 6,
                "prompt_eval_duration": 1_000_000_000,
                "eval_count": 9,
                "eval_duration": 2_000_000_000,
            }

        def model_digest(self, model):
            return "a" * 64

        def loaded_model_details(self, *, force_refresh=False):
            del force_refresh
            return [{"name": "qwen2.5-coder:7b", "vram_bytes": 400 * 1024 * 1024}]

    class Scheduler:
        def __init__(self) -> None:
            self.calls = 0

        def submit(self, model, *, source, execute, **kwargs):
            result = execute()
            result["_lah_scheduler_queue_wait_ms"] = 12.5
            result["_lah_scheduler_fairness_wait_ms"] = 3.5
            if self.calls == 0:
                result["_lah_scheduler_model_switch"] = {
                    "switch_event_id": 7,
                    "model": model,
                    "model_prepare_ms": 6.0,
                    "model_switch_ms": 8.0,
                    "evicted_models": ["old-model"],
                    "eviction_count": 1,
                    "vram_before_bytes": None,
                    "vram_after_bytes": 400 * 1024 * 1024,
                    "success": True,
                }
            self.calls += 1
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
    assert result["prefill_ms"] == 1000.0
    assert result["generation_ms"] == 2000.0
    assert result["inference_ms"] == 3000.0
    assert result["model_load_event"] is True
    assert result["model_reuse_event"] is False
    assert result["deadline_generation_ms"] == 2000.0
    assert result["fairness_wait_ms"] == 3.5
    assert result["switch_event_id"] == 7
    assert result["model_prepare_ms"] == 6.0
    assert result["model_switch_ms"] == 8.0
    assert result["evicted_models"] == ["old-model"]
    assert result["eviction_count"] == 1
    assert result["vram_before_bytes"] is None
    assert result["vram_after_bytes"] == 400 * 1024 * 1024
    assert result["model_switch_success"] is True
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

    runner.runtime.load_duration = 2_730_000
    warm_result = runner.run_t12_case(
        task="reason",
        model="qwen2.5-coder:7b",
        prompt="Return the expected structured answer.",
        num_tokens=8,
        expected={"answer": "42"},
        evidence_paths=[],
    )
    assert warm_result["load_duration_ms"] == 2.73
    assert warm_result["model_load_event"] is False
    assert warm_result["model_reuse_event"] is True

    runner.runtime.load_duration = 500_000_000
    cold_result = runner.run_t12_case(
        task="reason",
        model="qwen2.5-coder:7b",
        prompt="Return the expected structured answer.",
        num_tokens=8,
        expected={"answer": "42"},
        evidence_paths=[],
    )
    assert cold_result["model_load_event"] is True
    assert cold_result["model_reuse_event"] is False


def test_scheduler_tracks_same_priority_wait_and_oldest_first_order() -> None:
    from local_ai_hub.scheduler import AffinityScheduler, Job

    scheduler = object.__new__(AffinityScheduler)
    scheduler._active_model = "test-model"

    def job(job_id: int, created_at: float) -> Job:
        return Job(
            id=job_id,
            model="test-model",
            source="test",
            priority=1,
            execute=lambda: {"success": True},
            created_at=created_at,
        )

    first_a = job(1, 1.0)
    waiting_a = job(2, 3.0)
    first_b = job(3, 2.0)
    waiting_b = job(4, 4.0)

    assert scheduler._choose_job_for_active_model(10.0, [first_a, waiting_a, first_b, waiting_b]) is first_a
    assert scheduler._choose_job_for_active_model(11.0, [waiting_a, first_b, waiting_b]) is first_b
    assert scheduler._choose_job_for_active_model(13.0, [waiting_a, waiting_b]) is waiting_a

    assert waiting_a.fairness_wait_ms == 1000.0
    assert waiting_b.fairness_wait_ms == 3000.0


def test_scheduler_switch_receipt_records_eviction_and_vram_boundaries() -> None:
    from local_ai_hub.scheduler import AffinityScheduler, Job

    class Runtime:
        loaded = False

        def loaded_model_details(self, **kwargs):
            del kwargs
            if not self.loaded:
                return []
            return [{"name": "target-model", "vram_bytes": 512}]

        def prepare_model(self, model, **kwargs):
            del model, kwargs
            self.loaded = True
            return ["old-model"]

    scheduler = AffinityScheduler(Runtime(), {"scheduler": {}})
    try:
        scheduler._running = False
        scheduler._dispatcher.join(timeout=1.0)
        waiters = [
            Job(id=1, model="target-model", source="test", priority=1, execute=lambda: {"success": True})
            for index in range(2)
        ]
        with scheduler._cond:
            scheduler._pending.extend(waiters)

        assert scheduler._perform_switch("target-model") is True
        receipts = [job.model_switch_receipt for job in waiters]
        assert all(isinstance(receipt, dict) for receipt in receipts)
        assert receipts[0] == receipts[1]
        assert receipts[0]["switch_event_id"] == 1
        assert receipts[0]["evicted_models"] == ["old-model"]
        assert receipts[0]["eviction_count"] == 1
        assert receipts[0]["vram_before_bytes"] is None
        assert receipts[0]["vram_after_bytes"] == 512
        assert receipts[0]["success"] is True
        assert receipts[0]["model_switch_ms"] >= receipts[0]["model_prepare_ms"]
    finally:
        scheduler.close()


def test_t12_case_does_not_infer_throughput_without_backend_eval_duration(tmp_path: Path) -> None:
    class Runtime:
        def generate_stream(self, model, prompt, options=None):
            yield {"response": '{"answer":"42"}', "eval_count": 9}

    class Scheduler:
        def submit(self, model, *, source, execute, **kwargs):
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
        timeout = None

        def request_stream(self, endpoint, payload, on_chunk, timeout=None):
            assert endpoint == "/api/generate"
            assert payload["stream"] is True
            self.timeout = timeout
            time.sleep(0.01)
            on_chunk('{"answer":"42"}')
            return {
                "response": '{"answer":"42"}',
                "eval_count": 9,
                "eval_duration": 2_000_000_000,
            }

    class Scheduler:
        def submit(self, model, *, source, execute, **kwargs):
            return execute()

    runtime = Runtime()
    runner = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=runtime,
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
    assert runtime.timeout == 120.0
    assert result["ttft_ms"] > 0
    assert result["tokens_per_second"] == 4.5
    assert result["deadline_generation_ms"] == 2000.0


def test_t12_case_reports_vram_admission_rejection_instead_of_empty_response(tmp_path: Path) -> None:
    class Runtime:
        def request_stream(self, endpoint, payload, on_chunk, timeout=None):
            raise AssertionError("rejected admission must not invoke the runtime")

        def loaded_model_details(self, *, force_refresh=False):
            del force_refresh
            return []

    class Scheduler:
        def submit(self, model, *, source, execute, **kwargs):
            del model, source, execute, kwargs
            raise QueueFullError(
                "resource pressure blocks admission",
                admission={
                    "state": "rejected", "reason": "vram_budget", "vram_admission": "rejected",
                    "vram_admission_budget_bytes": 100, "vram_incremental_required_bytes": 200,
                    "vram_estimate_source": "measured",
                },
            )

    runner = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=Runtime(),
        scheduler=Scheduler(),
        config={"models": {"reasoning": "qwen2.5-coder:7b"}},
    )

    result = runner.run_t12_case(
        task="reason", model="qwen2.5-coder:7b", prompt="Return a structured answer.",
        num_tokens=8, expected={"answer": "42"}, evidence_paths=[],
    )

    assert result["success"] is False
    assert result["failure_code"] == "resource_exhausted"
    assert result["vram_admitted"] == "rejected"
    assert result["vram_admission_budget_bytes"] == 100
    assert result["vram_incremental_required_bytes"] == 200
    assert result["vram_estimate_source"] == "measured"


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
            "queued_count": 1, "rejected_count": 1, "resource_rejected_count": 0,
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
            "source_model": "primary-model",
            "fallback_model": "fallback-model",
            "source_backend": "ollama",
            "fallback_backend": "ollama",
            "source_quality_pct": 0.0,
            "source_quality_status": "scored",
            "quality_floor_pct": 80.0,
            "fallback_quality_pct": 85.0,
            "source_max_tokens": 2,
            "fallback_max_tokens": 32,
            "quality_floor_met": True,
        },
    }

    class Scheduler:
        def __init__(self) -> None:
            self.scenario_calls: list[tuple[str, dict[str, object]]] = []

        def submit(self, model, *, source, execute, **kwargs):
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

        def submit(self, model, *, source, execute, **kwargs):
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
        def submit(self, model, *, source, execute, **kwargs):
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


def test_t12_fallback_receipt_preserves_model_backend_and_quality_change() -> None:
    class Runner:
        config = {
            "models": {"reasoning": "primary-model", "fast_code": "fallback-model"},
            "_hardware": {"profile": "balanced"},
        }

        def run_benchmark_scenario(self, *, name: str, contract: dict[str, object]):
            self.contract = contract
            return {
                "fallback_used": True,
                "fallback_visible": True,
                "source_profile": "balanced",
                "fallback_profile": "fast_code",
                "source_model": "primary-model",
                "fallback_model": "fallback-model",
                "source_backend": "ollama",
                "fallback_backend": "ollama",
                "source_quality_pct": 0.0,
                "source_quality_status": "scored",
                "quality_floor_pct": 80.0,
                "fallback_quality_pct": 100.0,
                "source_max_tokens": 2,
                "fallback_max_tokens": 64,
                "quality_floor_met": True,
                "receipt_id": "t12:fallback-contract",
            }

    runner = Runner()
    report = _t12_scenario_report(
        runner, "fallback", concurrency_limit=1, quality_floor_pct=80.0, live_hardware=True,
    )

    assert report["accepted"] is True
    assert report["runner_receipt_id"] == "t12:fallback-contract"
    assert report["measurements"]["source_model"] == "primary-model"
    assert report["measurements"]["fallback_model"] == "fallback-model"
    assert report["measurements"]["source_backend"] == report["measurements"]["fallback_backend"] == "ollama"
    assert report["measurements"]["source_quality_pct"] == 0.0
    assert report["measurements"]["fallback_quality_pct"] == 100.0
    assert report["measurements"]["source_max_tokens"] == 2
    assert report["measurements"]["fallback_max_tokens"] == 64
    assert report["measurements"]["quality_floor_met"] is True
    assert runner.contract["scenario_inputs"]["source_max_tokens"] < runner.contract["scenario_inputs"]["fallback_max_tokens"]


def test_t12_integrated_fallback_uses_measured_quality_capable_model_and_budget() -> None:
    class Runner:
        config = {
            "models": {
                "reasoning": "qwen2.5-coder:7b",
                "fast_code": "qwen2.5-coder:1.5b",
                "heavy_code": "qwen2.5-coder:3b",
                "general": "qwen2.5-coder:1.5b",
            },
            "_hardware": {"profile": "integrated"},
        }

        def run_benchmark_scenario(self, *, name: str, contract: dict[str, object]):
            assert name == "fallback"
            inputs = contract["scenario_inputs"]
            self.inputs = inputs
            return {
                "fallback_used": True,
                "fallback_visible": True,
                "source_profile": "integrated",
                "fallback_profile": inputs["fallback_profile"],
                "source_model": inputs["model"],
                "fallback_model": inputs["fallback_model"],
                "source_backend": "ollama",
                "fallback_backend": "ollama",
                "source_quality_pct": 0.0,
                "source_quality_status": "scored",
                "quality_floor_pct": 80.0,
                "fallback_quality_pct": 100.0,
                "source_max_tokens": inputs["source_max_tokens"],
                "fallback_max_tokens": inputs["fallback_max_tokens"],
                "quality_floor_met": True,
                "receipt_id": "t12:integrated-fallback",
            }

    runner = Runner()
    report = _t12_scenario_report(
        runner, "fallback", concurrency_limit=1, quality_floor_pct=80.0, live_hardware=True,
    )

    assert report["accepted"] is True
    assert report["measurements"]["fallback_profile"] == "heavy_code"
    assert report["measurements"]["fallback_model"] == "qwen2.5-coder:3b"
    assert runner.inputs["source_max_tokens"] == 2
    assert runner.inputs["fallback_max_tokens"] == 64
    assert runner.inputs["max_tokens"] == 64


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
                "resource_rejected_count": 0,
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
                "structured_json_valid": True,
                "quality_schema_pass": True,
                "quality_expected_match": True,
                "quality_paths_grounded": True,
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
    assert sample["structured_json_valid"] is True
    assert sample["quality_schema_pass"] is True
    assert sample["quality_expected_match"] is True
    assert sample["quality_paths_grounded"] is True
    assert "fairness_wait_ms_missing" not in role["missing_acceptance"]
    assert "batch_size_missing" not in role["missing_acceptance"]
    assert "quality_diagnostics_missing" not in role["missing_acceptance"]


def test_t12_profile_matrix_requires_quality_diagnostics_for_live_acceptance() -> None:
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
            del task, kwargs
            return {
                "success": True,
                "model": model,
                "model_digest": "a" * 64,
                "routed_profile": "heavy_code",
                "quality_evaluator_id": "model_quality.evaluate_case:t12.v1",
                "quality_score_pct": 0.0,
            }

    result = _run_t12_matrix(
        Runner(), repetitions=1, concurrency_limit=2, quality_floor_pct=80.0, live_hardware=True,
    )

    role = result["task_roles"]["review"]
    assert role["quality"]["score_pct"] == 0.0
    assert role["samples"][0]["quality_expected_match"] is None
    assert "quality_diagnostics_missing" in role["missing_acceptance"]


def test_t12_quality_diagnostics_distinguish_structured_failure_modes(tmp_path: Path) -> None:
    class Runtime:
        response_text = ""

        def generate_stream(self, model, prompt, options=None):
            del model, prompt, options
            yield {"response": self.response_text}

        def model_digest(self, model):
            del model
            return "a" * 64

        def loaded_model_details(self, *, force_refresh=False):
            del force_refresh
            return [{"name": "test-model", "vram_bytes": 400 * 1024 * 1024}]

    class Scheduler:
        def submit(self, model, *, source, execute, **kwargs):
            del model, source, kwargs
            return execute()

    runtime = Runtime()
    runner = HardwareBenchmarkRunner(
        benchmarks_path=tmp_path / "benchmarks.json",
        runtime=runtime,
        scheduler=Scheduler(),
        config={"models": {"heavy_code": "test-model"}},
    )
    expected = {"answer": "42", "evidence_paths": ["benchmarks/t12/proof.json"]}
    cases = {
        "valid": ('{"answer":"42","evidence_paths":["benchmarks/t12/proof.json"]}', True, True, True, True, 100.0),
        "malformed_json": ('{"answer":"42","evidence_paths":["benchmarks/t12/proof.json"]', False, False, False, True, 0.0),
        "schema_mismatch": ('{"answer":42,"evidence_paths":["benchmarks/t12/proof.json"]}', True, False, False, True, 0.0),
        "expected_mismatch": ('{"answer":"41","evidence_paths":["benchmarks/t12/proof.json"]}', True, True, False, True, 0.0),
        "ungrounded_path": ('{"answer":"42","evidence_paths":["benchmarks/t12/unseen.json"]}', True, True, False, False, 0.0),
    }

    for response_text, json_valid, schema_pass, expected_match, paths_grounded, score in cases.values():
        runtime.response_text = response_text
        result = runner.run_t12_case(
            task="review",
            model="test-model",
            prompt="Return one JSON object.",
            num_tokens=32,
            expected=expected,
            evidence_paths=["benchmarks/t12/proof.json"],
        )

        assert result["structured_json_valid"] is json_valid
        assert result["quality_schema_pass"] is schema_pass
        assert result["quality_expected_match"] is expected_match
        assert result["quality_paths_grounded"] is paths_grounded
        assert result["quality_score_pct"] == score

    class MissingDiagnosticsRunner:
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
                "model_digest": "b" * 64,
                "routed_profile": routed_profile,
                "quality_evaluator_id": "model_quality.evaluate_case:t12.v1",
                "quality_score_pct": 0.0,
            }

    matrix = _run_t12_matrix(
        MissingDiagnosticsRunner(), repetitions=1, concurrency_limit=2,
        quality_floor_pct=80.0, live_hardware=True,
    )
    review_role = matrix["task_roles"]["review"]
    assert review_role["quality"]["score_pct"] == 0.0
    assert "quality_diagnostics_missing" in review_role["missing_acceptance"]
