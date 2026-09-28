from __future__ import annotations

import threading
import time
from typing import Any

from local_ai_hub.ollama import OllamaRuntime
from local_ai_hub.tiered_ollama import TieredOllamaRuntime


class _MeasuredScheduler:
    def __init__(self, *, result: dict[str, Any] | None = None) -> None:
        self.result = result or {}
        self.calls: list[dict[str, Any]] = []

    def submit(
        self,
        model: str,
        tenant: str,
        source: str,
        execute,
        priority: int = 5,
        wait_timeout: float | None = None,
        *,
        background: bool = False,
        cancel_event=None,
    ) -> dict[str, Any]:
        self.calls.append({
            "model": model,
            "tenant": tenant,
            "source": source,
            "wait_timeout": wait_timeout,
            "background": background,
            "cancel_event": cancel_event,
        })
        measured = execute()
        return {
            **measured,
            **self.result,
            "_lah_scheduler_queue_wait_ms": 2.0,
            "_lah_scheduler_service_ms": 25.0,
            "admission": {"state": "admitted", "queue_age_ms": 2.0},
        }


def test_t12_model_digest_uses_exact_installed_ollama_digest() -> None:
    runtime = object.__new__(OllamaRuntime)
    runtime._meta_cache = {}
    runtime._meta_cache_at = {}
    expected_digest = "a" * 64
    runtime.request = lambda endpoint, **kwargs: {
        "models": [{"name": "qwen2.5-coder:7b", "digest": f"sha256:{expected_digest}"}],
    }

    assert runtime.model_digest("qwen2.5-coder:7b") == expected_digest
    assert runtime.model_digest("other-model") is None


def test_t12_json_format_and_think_are_promoted_to_ollama_request_fields() -> None:
    runtime = object.__new__(OllamaRuntime)
    captured: dict[str, Any] = {}

    def request(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        captured.update({"endpoint": endpoint, **payload})
        return {"response": "{}"}

    runtime.request = request
    result = runtime.generate(
        "fixture-model",
        "Return JSON.",
        options={"num_predict": 16, "temperature": 0, "think": False, "format": "json"},
    )

    assert result == {"response": "{}"}
    assert captured["format"] == "json"
    assert captured["think"] is False
    assert captured["options"] == {"num_predict": 16, "temperature": 0}


def test_t12_ollama_runtime_measures_deadline_stages_through_scheduler() -> None:
    runtime = object.__new__(OllamaRuntime)
    runtime.config = {}
    request_calls: list[tuple[str, dict[str, Any], float | None]] = []

    def request_interruptible(
        endpoint: str,
        payload: dict[str, Any],
        should_stop,
        *,
        timeout: float | None = None,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        request_calls.append((endpoint, payload, timeout))
        return {
            "response": "fixture completion",
            "prompt_eval_count": 4,
            "prompt_eval_duration": 4_000_000,
            "eval_count": 2,
            "eval_duration": 20_000_000,
            "load_duration": 3_000_000,
        }

    runtime.request_interruptible = request_interruptible
    scheduler = _MeasuredScheduler()
    contract = {
        "scenario": "deadline",
        "required_fields": [
            "deadline_ms",
            "stages",
            "stage_timings_ms",
            "deadline_stage",
            "completed_within_deadline",
            "request_succeeded",
        ],
        "scenario_inputs": {
            "model": "fixture-model",
            "profile": "balanced",
            "items": [{"id": "item-1", "tenant": "tenant-a", "prompt": "Return OK"}],
            "max_tokens": 8,
            "deadline_ms": 1000,
        },
    }

    result = runtime.run_benchmark_scenario(
        name="deadline",
        contract=contract,
        scheduler=scheduler,
    )

    assert result["success"] is True
    assert result["scenario"] == "deadline"
    assert result["status"] == "measured"
    assert result["metrics"]["deadline_ms"] == 1000
    assert result["metrics"]["stages"] == ["queue", "model_load", "generation"]
    assert result["metrics"]["stage_timings_ms"] == {
        "queue": 2.0,
        "model_load": 3.0,
        "generation": 20.0,
    }
    assert result["metrics"]["deadline_stage"] == "generation"
    assert result["metrics"]["completed_within_deadline"] is True
    assert result["metrics"]["request_succeeded"] is True
    assert result["receipt_id"]
    assert scheduler.calls[0]["model"] == "fixture-model"
    assert scheduler.calls[0]["source"] == "t12-deadline"
    assert scheduler.calls[0]["wait_timeout"] == 1.0
    assert request_calls[0][0] == "/api/generate"
    assert request_calls[0][1]["prompt"] == "Return OK"
    assert 0 < request_calls[0][2] <= 1.0


def test_t12_runtime_overload_reports_observed_queueing() -> None:
    runtime = object.__new__(OllamaRuntime)
    runtime.config = {}

    def request_interruptible(endpoint, payload, should_stop, *, timeout=None, deadline=None):
        del endpoint, should_stop, timeout, deadline
        return {"response": payload["prompt"], "_lah_provider": "ollama"}

    runtime.request_interruptible = request_interruptible
    scheduler = _MeasuredScheduler()
    scheduler._pending = []
    scheduler._cond = threading.Condition()
    contract = {
        "scenario": "overload",
        "required_fields": ["overloaded", "queue_depth", "queue_admission", "queued_count", "rejected_count"],
        "scenario_inputs": {
            "model": "fixture-model",
            "profile": "balanced",
            "items": [
                {"id": "a", "tenant": "tenant-a", "prompt": "first"},
                {"id": "b", "tenant": "tenant-b", "prompt": "second"},
            ],
            "max_tokens": 8,
            "max_concurrency": 2,
        },
    }

    result = runtime.run_benchmark_scenario(name="overload", contract=contract, scheduler=scheduler)

    assert result["success"] is True
    assert result["metrics"]["overloaded"] is True
    assert result["metrics"]["queue_admission"] == "queued"
    assert result["metrics"]["queued_count"] == 2
    assert result["metrics"]["rejected_count"] == 0
    assert result["receipt_id"]


def test_t12_tiered_runtime_measures_through_its_routed_request_path() -> None:
    tiered = object.__new__(TieredOllamaRuntime)
    tiered.config = {}
    request_calls: list[dict[str, Any]] = []

    def request_interruptible(endpoint, payload, should_stop, *, timeout=None, deadline=None):
        request_calls.append({"endpoint": endpoint, "payload": payload, "deadline": deadline})
        return {"response": "fixture completion", "prompt_eval_count": 3, "_lah_provider": "ollama"}

    tiered.request_interruptible = request_interruptible
    scheduler = _MeasuredScheduler()
    contract = {
        "scenario": "scheduler",
        "required_fields": ["queue_age_ms", "prefill_tokens"],
        "scenario_inputs": {
            "model": "smart-model",
            "profile": "high",
            "items": [{"id": "item-1", "tenant": "tenant-a", "prompt": "Return OK"}],
            "max_tokens": 8,
        },
    }

    result = tiered.run_benchmark_scenario(
        name="scheduler",
        contract=contract,
        scheduler=scheduler,
    )

    assert result["success"] is True
    assert result["scenario"] == "scheduler"
    assert result["metrics"]["queue_age_ms"] == 2.0
    assert result["metrics"]["prefill_tokens"] == 3
    assert scheduler.calls[0]["model"] == "smart-model"
    assert scheduler.calls[0]["source"] == "t12-scheduler"
    assert request_calls[0]["payload"]["model"] == "smart-model"


def test_t12_ollama_runtime_fails_closed_without_complete_measurements() -> None:
    runtime = object.__new__(OllamaRuntime)
    runtime.config = {}
    scheduler = _MeasuredScheduler()
    runtime.request_interruptible = lambda *args, **kwargs: {
        "response": "fixture completion",
        "eval_count": 2,
        # Missing eval_duration and load_duration: receipt must not be emitted.
    }
    contract = {
        "scenario": "deadline",
        "required_fields": ["deadline_ms", "stage_timings_ms"],
        "scenario_inputs": {
            "model": "fixture-model",
            "profile": "balanced",
            "items": [{"id": "item-1", "tenant": "tenant-a", "prompt": "Return OK"}],
            "max_tokens": 8,
            "deadline_ms": 1000,
        },
    }

    result = runtime.run_benchmark_scenario(
        name="deadline",
        contract=contract,
        scheduler=scheduler,
    )

    assert result.get("success") is False
    assert "deadline_ms" not in result
    assert "stage_timings_ms" not in result
    assert "receipt_id" not in result


def test_t12_runtime_does_not_issue_receipt_when_vram_admission_is_unavailable() -> None:
    runtime = object.__new__(OllamaRuntime)
    runtime.config = {}
    runtime.request_interruptible = lambda *args, **kwargs: {
        "response": "fixture completion",
        "prompt_eval_count": 2,
    }
    contract = {
        "scenario": "scheduler",
        "required_fields": ["vram_budget_bytes", "vram_admission"],
        "scenario_inputs": {
            "model": "fixture-model",
            "profile": "balanced",
            "items": [{"id": "item-1", "tenant": "tenant-a", "prompt": "Return OK"}],
            "max_tokens": 8,
        },
    }

    result = runtime.run_benchmark_scenario(
        name="scheduler",
        contract=contract,
        scheduler=_MeasuredScheduler(),
    )

    assert result["success"] is False
    assert "receipt_id" not in result
    assert "vram_budget_bytes" not in result.get("metrics", {})
    assert "vram_admission" not in result.get("metrics", {})


def test_t12_scheduler_scenario_groups_by_prompt_size_and_reports_measured_batch() -> None:
    runtime = object.__new__(OllamaRuntime)
    runtime.config = {}
    runtime.request_interruptible = lambda endpoint, payload, should_stop, **kwargs: {
        "response": "OK",
        "prompt_eval_count": len(payload["prompt"]),
    }
    scheduler = _MeasuredScheduler()
    contract = {
        "scenario": "scheduler",
        "required_fields": ["bucket_id", "batch_size", "batch_item_count", "prefill_tokens"],
        "concurrency_limit": 1,
        "scenario_inputs": {
            "model": "fixture-model",
            "profile": "balanced",
            "items": [
                {"id": "short-a", "tenant": "tenant-a", "prompt": "abcdefgh"},
                {"id": "long", "tenant": "tenant-b", "prompt": "x" * 80},
                {"id": "short-b", "tenant": "tenant-a", "prompt": "ijklmnop"},
            ],
            "max_tokens": 8,
            "max_concurrency": 1,
        },
    }

    result = runtime.run_benchmark_scenario(
        name="scheduler",
        contract=contract,
        scheduler=scheduler,
    )

    assert result["success"] is True
    assert result["metrics"]["bucket_id"] == "prompt-bytes-p2-8"
    assert result["metrics"]["batch_size"] == 2
    assert result["metrics"]["batch_item_count"] == 3
    assert result["metrics"]["prefill_tokens"] == 96
    assert [call["tenant"] for call in scheduler.calls] == ["tenant-a", "tenant-a", "tenant-b"]


def test_t12_scheduler_scenario_forwards_admission_and_sampled_vram_bytes() -> None:
    runtime = object.__new__(OllamaRuntime)
    runtime.config = {}
    runtime.request_interruptible = lambda endpoint, payload, should_stop, **kwargs: {
        "response": "OK",
        "prompt_eval_count": 2,
    }
    runtime.loaded_model_details = lambda: [{"name": "fixture-model", "vram_bytes": 1234}]

    class Scheduler:
        def submit(self, model, tenant, source, execute, **kwargs):
            return {
                **execute(),
                "_lah_scheduler_queue_wait_ms": 2.0,
                "admission": {
                    "state": "accepted",
                    "queue_age_ms": 2.0,
                    "vram_admission": "admitted",
                    "vram_admission_budget_bytes": 6 * 1024 * 1024 * 1024,
                    "vram_incremental_required_bytes": 1234,
                    "vram_estimate_source": "measured",
                },
            }

    class ResourceSampler:
        def sample_vram(self) -> dict[str, Any]:
            return {
                "available": True,
                "vram_total_mb": 8192.0,
                "vram_used_mb": 1024.0,
                "vram_available_mb": 7168.0,
                "pressure_level": "nominal",
            }

    result = runtime.run_benchmark_scenario(
        name="scheduler",
        contract={
            "scenario": "scheduler",
            "required_fields": [
                "vram_admission", "vram_budget_bytes", "vram_available_bytes", "vram_required_bytes",
                "vram_admission_budget_bytes", "vram_incremental_required_bytes", "vram_estimate_source",
            ],
            "scenario_inputs": {
                "model": "fixture-model",
                "profile": "balanced",
                "items": [{"id": "item-1", "tenant": "tenant-a", "prompt": "Return OK"}],
                "max_tokens": 8,
                "max_concurrency": 1,
            },
        },
        scheduler=Scheduler(),
        resource_sampler=ResourceSampler(),
    )

    assert result["success"] is True
    assert result["metrics"]["vram_admission"] == "admitted"
    assert result["metrics"]["vram_budget_bytes"] == 8192 * 1024 * 1024
    assert result["metrics"]["vram_available_bytes"] == 7168 * 1024 * 1024
    assert result["metrics"]["vram_required_bytes"] == 1234
    assert result["metrics"]["vram_admission_budget_bytes"] == 6 * 1024 * 1024 * 1024
    assert result["metrics"]["vram_incremental_required_bytes"] == 1234
    assert result["metrics"]["vram_estimate_source"] == "measured"


def test_t12_runtime_batch_preserves_order_and_reports_partial_failure() -> None:
    runtime = object.__new__(OllamaRuntime)
    runtime.config = {}

    def request_interruptible(endpoint, payload, should_stop, *, timeout=None, deadline=None):
        if payload["prompt"] == "fail":
            return {"error": "fixture failure"}
        return {"response": payload["prompt"], "prompt_eval_count": 1, "_lah_provider": "ollama"}

    runtime.request_interruptible = request_interruptible
    scheduler = _MeasuredScheduler()
    contract = {
        "scenario": "batch",
        "required_fields": [
            "input_item_ids", "result_item_ids", "item_statuses", "partial_failure_count",
            "max_concurrency", "concurrency_limit",
        ],
        "scenario_inputs": {
            "model": "fixture-model",
            "profile": "balanced",
            "items": [
                {"id": "a", "tenant": "tenant-a", "prompt": "first"},
                {"id": "b", "tenant": "tenant-b", "prompt": "fail"},
                {"id": "c", "tenant": "tenant-a", "prompt": "third"},
            ],
            "failure_probe_item_id": "b",
            "max_tokens": 8,
            "max_concurrency": 2,
        },
    }

    result = runtime.run_benchmark_scenario(name="batch", contract=contract, scheduler=scheduler)

    assert result["success"] is True
    assert result["metrics"]["input_item_ids"] == ["a", "b", "c"]
    assert result["metrics"]["result_item_ids"] == ["a", "b", "c"]
    assert result["metrics"]["item_statuses"] == ["success", "failed", "success"]
    assert result["metrics"]["partial_failure_count"] == 1
    assert result["metrics"]["failure_probe_item_id"] == "b"
    assert result["metrics"]["failure_probe_observed"] is True
    assert 1 <= result["metrics"]["max_concurrency"] <= 2


def test_t12_runtime_cancel_measures_transport_stop_and_cleanup() -> None:
    runtime = object.__new__(OllamaRuntime)
    runtime.config = {}

    def request_interruptible(endpoint, payload, should_stop, *, timeout=None, deadline=None):
        while not should_stop():
            time.sleep(0.002)
        return {"success": False, "preempted": True, "_lah_provider": "ollama"}

    runtime.request_interruptible = request_interruptible
    scheduler = _MeasuredScheduler()
    contract = {
        "scenario": "cancel",
        "required_fields": ["cancel_requested", "cancelled", "cleanup_complete", "cancel_to_stop_ms"],
        "scenario_inputs": {
            "model": "fixture-model",
            "profile": "balanced",
            "items": [{"id": "cancel-1", "tenant": "tenant-a", "prompt": "long request"}],
            "max_tokens": 8,
            "deadline_ms": 1000,
            "cancel_after_ms": 10,
        },
    }

    result = runtime.run_benchmark_scenario(name="cancel", contract=contract, scheduler=scheduler)

    assert result["success"] is True
    assert result["metrics"]["cancel_requested"] is True
    assert result["metrics"]["cancelled"] is True
    assert result["metrics"]["cleanup_complete"] is True
    assert result["metrics"]["cancel_to_stop_ms"] >= 0


def test_t12_runtime_overload_reports_observed_admission_rejection() -> None:
    runtime = object.__new__(OllamaRuntime)
    runtime.config = {}
    runtime.request_interruptible = lambda *args, **kwargs: {"response": "OK"}

    class QueueFullError(RuntimeError):
        admission = {"state": "rejected", "reason": "queue_limit", "queue_age_ms": 0.0}

    class RejectingScheduler(_MeasuredScheduler):
        def submit(self, model, tenant, source, execute, priority=5, wait_timeout=None, *, background=False, cancel_event=None):
            if tenant == "tenant-b":
                raise QueueFullError("fixture queue full")
            return super().submit(
                model, tenant, source, execute, priority, wait_timeout,
                background=background, cancel_event=cancel_event,
            )

    scheduler = RejectingScheduler()
    contract = {
        "scenario": "overload",
        "required_fields": ["overloaded", "queue_admission"],
        "scenario_inputs": {
            "model": "fixture-model",
            "profile": "balanced",
            "items": [
                {"id": "a", "tenant": "tenant-a", "prompt": "first"},
                {"id": "b", "tenant": "tenant-b", "prompt": "second"},
            ],
            "max_tokens": 8,
            "max_concurrency": 2,
            "overload_count": 2,
        },
    }

    result = runtime.run_benchmark_scenario(name="overload", contract=contract, scheduler=scheduler)

    assert result["success"] is True
    assert result["metrics"]["overloaded"] is True
    assert result["metrics"]["queue_admission"] == "rejected"


def test_t12_runtime_fallback_scores_observed_response_and_labels_backends() -> None:
    runtime = object.__new__(OllamaRuntime)
    runtime.config = {"ollama": {"enabled": True}}

    def request_interruptible(endpoint, payload, should_stop, *, timeout=None, deadline=None):
        answer = "wrong" if payload["model"] == "source-model" else "42"
        return {"response": '{"answer":"' + answer + '"}', "_lah_provider": "ollama"}

    runtime.request_interruptible = request_interruptible
    scheduler = _MeasuredScheduler()
    contract = {
        "scenario": "fallback",
        "required_fields": [
            "fallback_used", "fallback_visible", "source_profile", "fallback_profile",
            "quality_floor_pct", "fallback_quality_pct", "quality_floor_met",
        ],
        "scenario_inputs": {
            "model": "source-model",
            "profile": "reasoning",
            "fallback_model": "fallback-model",
            "fallback_profile": "review",
            "quality_floor_pct": 80,
            "expected": {"answer": "42"},
            "items": [{"id": "fallback-1", "tenant": "tenant-a", "prompt": "Return JSON"}],
            "max_tokens": 8,
        },
    }

    result = runtime.run_benchmark_scenario(name="fallback", contract=contract, scheduler=scheduler)

    assert result["success"] is True
    assert result["metrics"]["fallback_used"] is True
    assert result["metrics"]["fallback_visible"] is True
    assert result["metrics"]["fallback_quality_pct"] == 100.0
    assert result["metrics"]["quality_floor_met"] is True
    assert result["metrics"]["source_backend"] == "ollama"
    assert result["metrics"]["fallback_backend"] == "ollama"
