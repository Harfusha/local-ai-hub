from __future__ import annotations

from .json_utils import dumps as json_dumps

import json
import math
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from . import model_quality


_T12_EVALUATOR_ID = "model_quality.evaluate_case:t12.v1"
_T12_TASK_MODEL_KEYS = {
    "reason": "reasoning",
    "review": "heavy_code",
    "compress": "fast_code",
    "complete": "fast_code",
    "scaffold": "heavy_code",
}
_T12_SCENARIO_NAMES = frozenset({"scheduler", "batch", "deadline", "overload", "cancel", "fallback"})


class HardwareBenchmarkRunner:
    """Hardware capability and inference latency benchmark harness.

    Measures Time-To-First-Token (TTFT), token generation throughput (TPS),
    VRAM footprint, and computes composite hardware performance ratings.
    """

    def __init__(
        self,
        benchmarks_path: Path | str,
        runtime: Any = None,
        vram_balancer: Any = None,
        config: dict[str, Any] | None = None,
        scheduler: Any = None,
    ) -> None:
        self.benchmarks_path = Path(benchmarks_path)
        self.runtime = runtime
        self.vram_balancer = vram_balancer
        self.config = config or {}
        self.scheduler = scheduler

    def _default_model(self) -> str:
        return str(self.config.get("models", {}).get("fast_code", "qwen2.5-coder:1.5b"))

    def run_t12_case(
        self,
        *,
        task: str,
        model: str,
        prompt: str,
        num_tokens: int,
        expected: dict[str, Any],
        evidence_paths: list[str],
    ) -> dict[str, Any]:
        """Run one live T12 case and persist only measured, prompt-free data."""
        if not self.runtime:
            return {"success": False, "error": "Runtime not configured for T12 benchmark"}
        if not callable(getattr(self.scheduler, "submit", None)):
            return {"success": False, "error": "Scheduler not configured for T12 benchmark"}

        models = self.config.get("models", {})
        if not isinstance(models, Mapping):
            models = {}
        requested_model = str(model or "").strip()
        routed_profile: str | None = None
        if requested_model in models:
            target_model = str(models[requested_model])
            routed_profile = requested_model
        elif requested_model:
            target_model = requested_model
        else:
            target_model = str(models.get("fast_code", self._default_model()))
            if "fast_code" in models:
                routed_profile = "fast_code"

        task_profile = _T12_TASK_MODEL_KEYS.get(str(task).strip().casefold())
        if task_profile and task_profile in models and str(models[task_profile]) == target_model:
            routed_profile = task_profile
        elif routed_profile is None:
            matching_profiles = [key for key, value in models.items() if str(value) == target_model]
            if len(matching_profiles) == 1:
                routed_profile = str(matching_profiles[0])

        response_parts: list[str] = []
        backend_metrics: dict[str, int] = {}
        first_visible_token_at: float | None = None
        sampled_vram_bytes: list[int] = []
        sampled_vram_lock = threading.Lock()
        sampler_stop = threading.Event()
        sampler_thread: threading.Thread | None = None

        def sample_vram() -> None:
            callback = getattr(self.vram_balancer, "sample_vram", None)
            if not callable(callback):
                return
            try:
                sample = callback()
            except Exception:
                return
            if not isinstance(sample, Mapping) or sample.get("available") is False:
                return
            used_mb = sample.get("vram_used_mb")
            if (
                isinstance(used_mb, bool)
                or not isinstance(used_mb, (int, float))
                or not math.isfinite(used_mb)
                or used_mb < 0
            ):
                return
            value = int(round(float(used_mb) * 1024 * 1024))
            with sampled_vram_lock:
                sampled_vram_bytes.append(value)

        def sample_vram_loop() -> None:
            while not sampler_stop.is_set():
                sample_vram()
                if sampler_stop.wait(0.1):
                    return

        def record_backend_metrics(chunk: Mapping[str, Any]) -> None:
            load_duration = chunk.get("load_duration")
            if (
                not isinstance(load_duration, bool)
                and isinstance(load_duration, (int, float))
                and math.isfinite(load_duration)
                and load_duration >= 0
            ):
                backend_metrics["load_duration_ns"] = int(load_duration)
            prefill_count = chunk.get("prompt_eval_count")
            if (
                not isinstance(prefill_count, bool)
                and isinstance(prefill_count, (int, float))
                and math.isfinite(prefill_count)
                and prefill_count >= 0
            ):
                backend_metrics["prefill_tokens"] = int(prefill_count)
            eval_count = chunk.get("eval_count")
            if (
                not isinstance(eval_count, bool)
                and isinstance(eval_count, int)
                and eval_count >= 0
            ):
                backend_metrics["eval_count"] = eval_count
            eval_duration = chunk.get("eval_duration")
            if (
                not isinstance(eval_duration, bool)
                and isinstance(eval_duration, (int, float))
                and math.isfinite(eval_duration)
                and eval_duration > 0
            ):
                backend_metrics["eval_duration_ns"] = int(eval_duration)

        def append_visible(value: Any, *, streamed: bool = True) -> None:
            nonlocal first_visible_token_at
            visible = str(value or "")
            if visible:
                if streamed and first_visible_token_at is None:
                    first_visible_token_at = time.perf_counter()
                response_parts.append(visible)

        options = {
            "num_predict": max(1, int(num_tokens)),
            "think": False,
            "format": "json",
            "temperature": 0,
        }

        def execute() -> dict[str, Any]:
            nonlocal sampler_thread
            if callable(getattr(self.vram_balancer, "sample_vram", None)):
                sampler_thread = threading.Thread(target=sample_vram_loop, name="t12-vram-sampler", daemon=True)
                sampler_thread.start()
            try:
                stream = getattr(self.runtime, "generate_stream", None)
                if callable(stream):
                    for chunk in stream(
                        target_model,
                        prompt,
                        options=options,
                    ):
                        if isinstance(chunk, Mapping):
                            if chunk.get("error"):
                                return {"success": False, "error": str(chunk["error"])}
                            record_backend_metrics(chunk)
                            append_visible(chunk.get("response", chunk.get("text", "")))
                        else:
                            append_visible(chunk)
                    return {"success": bool(response_parts)}

                request_stream = getattr(self.runtime, "request_stream", None)
                if callable(request_stream):
                    response = request_stream(
                        "/api/generate",
                        {
                            "model": target_model,
                            "prompt": prompt,
                            "stream": True,
                            "options": {
                                key: value for key, value in options.items()
                                if key not in {"think", "format"}
                            },
                            "think": False,
                            "format": "json",
                        },
                        append_visible,
                        timeout=None,
                    )
                    if not isinstance(response, Mapping):
                        return {"success": False, "error": "Runtime returned a non-object response"}
                    if response.get("error") or response.get("success") is False:
                        return {"success": False, "error": str(response.get("error") or "Runtime request failed")}
                    record_backend_metrics(response)
                    if not response_parts:
                        append_visible(response.get("response", response.get("text", "")), streamed=False)
                    return {"success": bool(response_parts)}

                generate = getattr(self.runtime, "generate", None)
                if not callable(generate):
                    return {"success": False, "error": "Runtime does not support generation"}
                response = generate(
                    target_model,
                    prompt,
                    options=options,
                )
                if not isinstance(response, Mapping):
                    return {"success": False, "error": "Runtime returned a non-object response"}
                if response.get("error"):
                    return {"success": False, "error": str(response["error"])}
                record_backend_metrics(response)
                append_visible(response.get("response", response.get("text", "")), streamed=False)
                return {"success": bool(response_parts)}
            finally:
                sampler_stop.set()
                if sampler_thread is not None:
                    sampler_thread.join(timeout=0.5)

        call_started_at = time.perf_counter()
        scheduler_result: Mapping[str, Any] = {}
        submit_error = ""
        server_config = self.config.get("server", {})
        server_config = server_config if isinstance(server_config, Mapping) else {}
        configured_timeout = server_config.get(
            "request_timeout_seconds",
            getattr(self.scheduler, "default_caller_wait_timeout", 120.0),
        )
        try:
            wait_timeout = max(0.05, min(120.0, float(configured_timeout)))
            scheduler_limit = getattr(self.scheduler, "max_caller_wait_timeout", wait_timeout)
            if isinstance(scheduler_limit, (int, float)) and not isinstance(scheduler_limit, bool):
                wait_timeout = min(wait_timeout, max(0.05, float(scheduler_limit)))
        except (TypeError, ValueError, OverflowError):
            wait_timeout = 30.0
        try:
            scheduler_result_raw = self.scheduler.submit(
                target_model, "benchmark", "benchmark", execute, priority=2, wait_timeout=wait_timeout,
            )
            if isinstance(scheduler_result_raw, Mapping):
                scheduler_result = scheduler_result_raw
            else:
                submit_error = "scheduler_invalid_result"
        except Exception as exc:
            submit_error = type(exc).__name__
        call_finished_at = time.perf_counter()

        measurements: dict[str, Any] = {}
        measurements["end_to_end_latency_ms"] = round(
            max(0.0, (call_finished_at - call_started_at) * 1000), 2
        )
        queue_wait_ms = scheduler_result.get("_lah_scheduler_queue_wait_ms")
        if (
            not isinstance(queue_wait_ms, bool)
            and isinstance(queue_wait_ms, (int, float))
            and math.isfinite(queue_wait_ms)
            and queue_wait_ms >= 0
        ):
            measurements["queue_wait_ms"] = round(float(queue_wait_ms), 2)
        admission = scheduler_result.get("admission")
        queue_age_ms = admission.get("queue_age_ms") if isinstance(admission, Mapping) else None
        if (
            isinstance(queue_age_ms, bool)
            or not isinstance(queue_age_ms, (int, float))
            or not math.isfinite(queue_age_ms)
            or queue_age_ms < 0
        ):
            queue_age_ms = queue_wait_ms
        if (
            not isinstance(queue_age_ms, bool)
            and isinstance(queue_age_ms, (int, float))
            and math.isfinite(queue_age_ms)
            and queue_age_ms >= 0
        ):
            measurements["queue_age_ms"] = round(float(queue_age_ms), 2)
            measurements["deadline_queue_ms"] = round(float(queue_age_ms), 2)
        if first_visible_token_at is not None:
            measurements["ttft_ms"] = round(max(0.0, (first_visible_token_at - call_started_at) * 1000), 2)
        load_duration_ns = backend_metrics.get("load_duration_ns")
        if load_duration_ns is not None:
            measurements["load_duration_ms"] = round(load_duration_ns / 1_000_000, 2)
            measurements["deadline_model_load_ms"] = measurements["load_duration_ms"]
            measurements["model_load_event"] = load_duration_ns > 0
            measurements["model_reuse_event"] = load_duration_ns == 0
        eval_duration_ns = backend_metrics.get("eval_duration_ns")
        if eval_duration_ns is not None:
            measurements["deadline_generation_ms"] = round(eval_duration_ns / 1_000_000, 2)
            eval_count = backend_metrics.get("eval_count")
            if eval_count is not None and eval_count > 0:
                measurements["tokens_per_second"] = round(
                    eval_count / (eval_duration_ns / 1_000_000_000), 2
                )
        if "prefill_tokens" in backend_metrics:
            measurements["prefill_tokens"] = backend_metrics["prefill_tokens"]
        admission = admission if isinstance(admission, Mapping) else {}
        for source_key, result_key in (
            ("vram_budget_bytes", "vram_budget_bytes"),
            ("vram_available_bytes", "vram_available_bytes"),
        ):
            value = admission.get(source_key)
            if (
                not isinstance(value, bool)
                and isinstance(value, (int, float))
                and math.isfinite(value)
                and value >= 0
            ):
                measurements[result_key] = int(value)
        vram_admission = admission.get("vram_admission")
        if isinstance(vram_admission, str) and vram_admission in {"admitted", "rejected"}:
            measurements["vram_admitted"] = vram_admission

        loaded_model_details = getattr(self.runtime, "loaded_model_details", None)
        if callable(loaded_model_details):
            try:
                try:
                    loaded_rows = loaded_model_details(force_refresh=True)
                except TypeError:
                    loaded_rows = loaded_model_details()
            except Exception:
                loaded_rows = []
            loaded_rows = loaded_rows if isinstance(loaded_rows, list) else []
            matching_vram = [
                row["vram_bytes"] for row in loaded_rows
                if isinstance(row, Mapping)
                and str(row.get("name", row.get("model", ""))).strip().casefold() == target_model.casefold()
                and isinstance(row.get("vram_bytes"), (int, float))
                and not isinstance(row.get("vram_bytes"), bool)
                and math.isfinite(row["vram_bytes"])
                and row["vram_bytes"] > 0
            ]
            if matching_vram:
                measurements["vram_required_bytes"] = int(sum(matching_vram))
                measurements["vram_required_source"] = "loaded_model_details"
        with sampled_vram_lock:
            if sampled_vram_bytes:
                measurements["peak_vram_bytes"] = max(sampled_vram_bytes)
                measurements["peak_vram_scope"] = "device_wide_sampled_during_inference"

        digest_provider = getattr(self.runtime, "model_digest", None)
        if callable(digest_provider):
            try:
                model_digest = digest_provider(target_model)
            except Exception:
                model_digest = None
            if isinstance(model_digest, str) and model_digest:
                measurements["model_digest"] = model_digest

        deadline_ms = round(wait_timeout * 1000.0, 2)
        measurements["deadline_ms"] = deadline_ms
        measurements["deadline_exceeded"] = measurements["end_to_end_latency_ms"] > deadline_ms
        if measurements["deadline_exceeded"]:
            queue_ms = measurements.get("deadline_queue_ms", 0.0)
            load_ms = measurements.get("deadline_model_load_ms", 0.0)
            if isinstance(queue_ms, (int, float)) and queue_ms >= deadline_ms:
                measurements["deadline_stage"] = "queue"
            elif (
                isinstance(queue_ms, (int, float)) and isinstance(load_ms, (int, float))
                and queue_ms + load_ms >= deadline_ms
            ):
                measurements["deadline_stage"] = "model_load"
            else:
                measurements["deadline_stage"] = "generation"
        else:
            measurements["deadline_stage"] = "generation"

        response_text = "".join(response_parts)
        structured_json_valid = False
        try:
            structured_output = json.loads(response_text) if response_text else {}
            structured_json_valid = bool(response_text)
        except (TypeError, ValueError):
            structured_output = {}
        try:
            evaluation = model_quality.evaluate_case(
                str(task),
                evidence_paths if isinstance(evidence_paths, list) else [],
                structured_output,
                expected if isinstance(expected, Mapping) else {},
            )
            quality_score_pct = round(float(evaluation.get("grounded_relevance", 0.0)) * 100, 2)
            quality_schema_pass = bool(evaluation.get("schema_pass"))
            quality_expected_match = bool(model_quality._expected_matches(
                structured_output if isinstance(structured_output, Mapping) else {},
                expected if isinstance(expected, Mapping) else {},
            ))
            quality_paths_grounded = not bool(evaluation.get("hallucinated_paths"))
        except Exception as exc:
            quality_score_pct = None
            quality_schema_pass = False
            quality_expected_match = False
            quality_paths_grounded = False
            if not submit_error:
                submit_error = "quality_evaluator_failed"

        success = bool(scheduler_result.get("success", bool(response_text))) and bool(response_text) and not submit_error
        if success:
            failure_code = None
        else:
            error_detail = str(scheduler_result.get("error") or submit_error or "").casefold()
            if any(term in error_detail for term in ("timeout", "timed out", "deadline")):
                failure_code = "request_timeout"
            elif any(term in error_detail for term in ("out of memory", "not enough memory", "failed to allocate", "vram")):
                failure_code = "resource_exhausted"
            elif any(term in error_detail for term in ("modelunavailable", "model not found", "model unavailable")):
                failure_code = "model_unavailable"
            elif any(term in error_detail for term in ("connection refused", "connection error", "backend unavailable")):
                failure_code = "backend_unavailable"
            elif "cancel" in error_detail:
                failure_code = "cancelled"
            elif "runtimeerror" in error_detail:
                failure_code = "runtime_error"
            elif not response_text:
                failure_code = "empty_response"
            elif submit_error:
                failure_code = "scheduler_submission_failed"
            elif scheduler_result.get("error"):
                failure_code = "runtime_request_failed"
            else:
                failure_code = "inference_failed"
        case_result: dict[str, Any] = {
            "success": success,
            "model": target_model,
            "quality_evaluator_id": _T12_EVALUATOR_ID,
            "structured_json_valid": structured_json_valid,
            "quality_schema_pass": quality_schema_pass,
            "quality_expected_match": quality_expected_match,
            "quality_paths_grounded": quality_paths_grounded,
            **measurements,
        }
        if failure_code:
            case_result["failure_code"] = failure_code
        if quality_score_pct is not None:
            case_result["quality_score_pct"] = quality_score_pct
        if routed_profile is not None:
            case_result["routed_profile"] = routed_profile
        hardware_profile = self.config.get("_hardware")
        if hardware_profile is not None:
            case_result["hardware_profile"] = hardware_profile
        error = submit_error or str(scheduler_result.get("error", "") or "")
        if error:
            case_result["error"] = error

        record: dict[str, Any] = {
            "record_type": "t12_case",
            "timestamp": time.time(),
            "model": target_model,
            "quality_evaluator_id": _T12_EVALUATOR_ID,
            "quality_score_pct": quality_score_pct,
            "success": success,
        }
        if routed_profile is not None:
            record["routed_profile"] = routed_profile
        record.update(measurements)
        record.update({
            "structured_json_valid": structured_json_valid,
            "quality_schema_pass": quality_schema_pass,
            "quality_expected_match": quality_expected_match,
            "quality_paths_grounded": quality_paths_grounded,
        })
        self._persist_record(record)
        return case_result

    def run_benchmark_scenario(self, *, name: str, contract: Mapping[str, Any]) -> dict[str, Any]:
        """Forward a T12 scenario contract to scheduler-owned instrumentation.

        Scenario measurements are never synthesized here. The runner only
        exposes all requested fields with the executor's receipt ID.
        """
        if not isinstance(name, str) or name not in _T12_SCENARIO_NAMES:
            return {"success": False, "error_type": "unsupported_scenario"}
        if not isinstance(contract, Mapping) or contract.get("scenario") != name:
            return {"success": False, "error_type": "invalid_scenario_contract"}
        required_fields = contract.get("required_fields")
        if (
            not isinstance(required_fields, list)
            or not required_fields
            or len(required_fields) > 64
            or any(
                not isinstance(field, str)
                or not field
                or field in {"success", "error_type", "scenario", "status", "metrics", "receipt_id"}
                for field in required_fields
            )
            or len(set(required_fields)) != len(required_fields)
        ):
            return {"success": False, "error_type": "invalid_scenario_contract"}

        execute_scenario = getattr(self.scheduler, "run_benchmark_scenario", None)
        if not callable(execute_scenario):
            return {"success": False, "error_type": "scenario_executor_unavailable"}
        try:
            scenario_args: dict[str, Any] = {"name": name, "contract": dict(contract)}
            if callable(getattr(self.vram_balancer, "sample_vram", None)):
                scenario_args["resource_sampler"] = self.vram_balancer
            result = execute_scenario(**scenario_args)
        except Exception as exc:
            return {"success": False, "error_type": type(exc).__name__}
        if not isinstance(result, Mapping):
            return {"success": False, "error_type": "scenario_execution_failed"}
        if result.get("success") is False:
            error_type = result.get("error_type")
            if not isinstance(error_type, str) or not error_type.isidentifier():
                error_type = "scenario_execution_failed"
            report: dict[str, Any] = {"success": False, "error_type": error_type}
            missing_fields = result.get("missing_fields")
            if isinstance(missing_fields, list):
                report["missing_fields"] = sorted({
                    field for field in missing_fields
                    if isinstance(field, str) and field and len(field) <= 128
                })
            return report

        measurements = {field: result[field] for field in required_fields if field in result}
        receipt_id = result.get("receipt_id")
        if (
            len(measurements) != len(set(required_fields))
            or any(value is None for value in measurements.values())
            or not isinstance(receipt_id, str)
            or not receipt_id.strip()
        ):
            return {"success": False, "error_type": "scenario_evidence_incomplete"}

        report: dict[str, Any] = {"success": True, **measurements}
        report["receipt_id"] = receipt_id.strip()
        return report

    def run(
        self,
        model: str = "",
        prompt: str = "def fibonacci(n: int) -> int:\n    \"\"\"Compute fibonacci recursively.\"\"\"\n",
        num_tokens: int = 40,
    ) -> dict[str, Any]:
        target_model = model.strip() or self._default_model()
        if not self.runtime:
            return {"success": False, "error": "Runtime not configured for benchmark"}

        initial_vram = {}
        if self.vram_balancer and hasattr(self.vram_balancer, "sample_vram"):
            try:
                initial_vram = self.vram_balancer.sample_vram()
            except Exception:
                pass

        t0 = time.perf_counter()
        first_token_time: float | None = None
        tokens_count = 0
        token_count_estimated = True
        response_text = ""
        thinking_chars = 0
        generation_duration_ns: int | None = None
        load_duration_ns: int | None = None
        streaming = False

        try:
            if callable(getattr(self.runtime, "generate_stream", None)):
                streaming = True
                # Qwen reasoning models can spend the whole small benchmark budget
                # in a hidden thinking stream.  Hardware routing needs visible
                # generation latency, so explicitly disable thinking here.
                for chunk in self.runtime.generate_stream(
                    target_model,
                    prompt,
                    options={"num_predict": num_tokens, "think": False},
                ):
                    if isinstance(chunk, dict) and chunk.get("error"):
                        return {"success": False, "model": target_model, "error": str(chunk["error"])}
                    if isinstance(chunk, dict):
                        load_duration = chunk.get("load_duration")
                        if isinstance(load_duration, (int, float)) and math.isfinite(load_duration) and load_duration >= 0:
                            load_duration_ns = int(load_duration)
                        eval_count = chunk.get("eval_count")
                        if isinstance(eval_count, (int, float)) and math.isfinite(eval_count) and eval_count > 0:
                            tokens_count = int(eval_count)
                            token_count_estimated = False
                        eval_duration = chunk.get("eval_duration")
                        if isinstance(eval_duration, (int, float)) and math.isfinite(eval_duration) and eval_duration > 0:
                            generation_duration_ns = int(eval_duration)
                        visible = str(chunk.get("response", chunk.get("text", "")) or "")
                        response_text += visible
                        thinking_chars += len(str(chunk.get("thinking", "") or ""))
                    else:
                        visible = str(chunk or "")
                        response_text += visible
                    if visible and first_token_time is None:
                        first_token_time = time.perf_counter()
                if not response_text and thinking_chars:
                    return {
                        "success": False,
                        "model": target_model,
                        "error": "benchmark produced thinking-only output",
                        "measurement_warning": "thinking_only_output",
                        "thinking_chars": thinking_chars,
                    }
            elif callable(getattr(self.runtime, "generate", None)):
                res = self.runtime.generate(
                    target_model,
                    prompt,
                    options={"num_predict": max(1, int(num_tokens)), "think": False},
                )
                if not isinstance(res, dict):
                    return {"success": False, "model": target_model, "error": "benchmark runtime returned a non-object response"}
                if res.get("error"):
                    return {"success": False, "model": target_model, "error": str(res["error"])}
                response_text = str(res.get("response", res.get("text", "")) or "")
                thinking_chars = len(str(res.get("thinking", "") or ""))
                tokens_count = int(res.get("eval_count", 0) or 0)
                token_count_estimated = tokens_count <= 0
                generation_duration_ns = int(res.get("eval_duration", 0) or 0) or None
                load_duration = res.get("load_duration")
                if isinstance(load_duration, (int, float)) and math.isfinite(load_duration) and load_duration >= 0:
                    load_duration_ns = int(load_duration)
                if not response_text:
                    return {
                        "success": False,
                        "model": target_model,
                        "error": "benchmark produced no visible output",
                        "measurement_warning": "thinking_only_output" if thinking_chars else "empty_visible_output",
                        "thinking_chars": thinking_chars,
                    }
            else:
                return {"success": False, "error": "Runtime does not support generation"}
        except Exception as exc:
            return {"success": False, "error": f"Benchmark generation failed: {exc}", "model": target_model}

        if not response_text:
            return {
                "success": False,
                "model": target_model,
                "error": "benchmark produced no visible output",
                "measurement_warning": "thinking_only_output" if thinking_chars else "empty_visible_output",
                "thinking_chars": thinking_chars,
            }
        if tokens_count <= 0:
            tokens_count = len(response_text.split())
            token_count_estimated = True

        t_end = time.perf_counter()

        ttft_ms = round((first_token_time - t0) * 1000, 2) if first_token_time else round((t_end - t0) * 1000, 2)
        gen_duration = max(0.001, (generation_duration_ns / 1e9) if generation_duration_ns else t_end - (first_token_time or t0) if streaming else t_end - t0)
        tps = round(tokens_count / gen_duration, 2) if tokens_count > 0 else 0.0

        # Composite score 0..100 based on TTFT and TPS
        score: float | None
        measurement_warning = ""
        if tokens_count < 2:
            score = None
            measurement_warning = "insufficient_output_tokens"
        else:
            # Use a smooth score: the previous hard 500 ms TTFT cutoff made
            # every realistic Windows model score the same 60/100 once TTFT was
            # above the cutoff.  This keeps 0..100 bounded while preserving
            # meaningful separation for routing and benchmark history.
            tps_part = min(60.0, (tps / 100.0) * 60.0)
            ttft_part = min(40.0, 40.0 * math.exp(-max(0.0, ttft_ms) / 3000.0))
            score = round(tps_part + ttft_part, 1)

        final_vram = {}
        if self.vram_balancer and hasattr(self.vram_balancer, "sample_vram"):
            try:
                final_vram = self.vram_balancer.sample_vram()
            except Exception:
                pass

        record: dict[str, Any] = {
            "timestamp": time.time(),
            "model": target_model,
            "tokens_generated": tokens_count,
            "token_count_estimated": token_count_estimated,
            "whitespace_token_estimate": tokens_count if token_count_estimated else None,
            "token_count_method": (
                "whitespace_token_estimate_not_model_tokenization"
                if token_count_estimated
                else "backend_eval_count"
            ),
            "ttft_ms": ttft_ms,
            "tokens_per_second": tps,
            "hardware_score": score,
            "generation_duration_ms": round(gen_duration * 1000, 2),
            "load_duration_ms": round(load_duration_ns / 1_000_000, 2) if load_duration_ns is not None else None,
            "output_chars": len(response_text),
            "streaming": streaming,
            "initial_vram": initial_vram,
            "final_vram": final_vram,
        }
        if measurement_warning:
            record["measurement_warning"] = measurement_warning

        self._persist_record(record)
        return {"success": True, **record}

    def _persist_record(self, record: dict[str, Any]) -> None:
        try:
            self.benchmarks_path.parent.mkdir(parents=True, exist_ok=True)
            history: list[dict[str, Any]] = []
            if self.benchmarks_path.exists():
                try:
                    history = json.loads(self.benchmarks_path.read_text(encoding="utf-8"))
                    if not isinstance(history, list):
                        history = []
                except Exception:
                    history = []
            history.append(record)
            if len(history) > 50:
                history = history[-50:]
            self.benchmarks_path.write_text(json_dumps(history, indent=2), encoding="utf-8")
        except Exception:
            pass

    def get_latest_summary(self) -> dict[str, Any]:
        if not self.benchmarks_path.exists():
            return {"available": False}
        try:
            history = json.loads(self.benchmarks_path.read_text(encoding="utf-8"))
            if not history or not isinstance(history, list):
                return {"available": False}
            latest = next(
                (
                    record
                    for record in reversed(history)
                    if isinstance(record, dict) and record.get("record_type") != "t12_case"
                ),
                None,
            )
            if latest is None:
                return {"available": False}
            return {
                "available": True,
                "model": latest.get("model", ""),
                "ttft_ms": latest.get("ttft_ms", 0.0),
                "tokens_per_second": latest.get("tokens_per_second", 0.0),
                "hardware_score": latest.get("hardware_score", 0.0),
                "timestamp": latest.get("timestamp", 0.0),
            }
        except Exception:
            return {"available": False}

    def history(self, limit: int = 10) -> list[dict[str, Any]]:
        if not self.benchmarks_path.exists():
            return []
        try:
            data = json.loads(self.benchmarks_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data[-limit:]
            return []
        except Exception:
            return []
