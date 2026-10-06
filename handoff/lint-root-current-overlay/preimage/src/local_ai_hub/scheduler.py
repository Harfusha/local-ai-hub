from __future__ import annotations

import contextvars
import math
import threading
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from .model_policy import ModelExecutionPolicy
from .trace_context import observer


_T12_SCENARIO_NAMES = frozenset({"scheduler", "batch", "deadline", "overload", "cancel", "fallback"})
_T12_RESERVED_FIELDS = frozenset({"success", "error_type", "scenario", "status", "metrics", "receipt_id"})
_T12_FIXTURE_CONTRACT_FIELDS = frozenset({"fixture", "fixture_metrics", "measurements", "observations", "receipt_id", "results"})


def _bounded_json_copy(value: Any, budget: list[int], depth: int = 0) -> Any:
    """Copy bounded JSON data for benchmark contracts and observed metrics."""
    if depth > 8 or budget[0] >= 2048:
        raise ValueError("scenario_value_limit")
    budget[0] += 1

    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        budget[1] += len(value)
        if len(value) > 4096 or budget[1] > 16384:
            raise ValueError("scenario_value_limit")
        return value
    if isinstance(value, int):
        if value.bit_length() > 63:
            raise ValueError("scenario_value_limit")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("scenario_value_limit")
        return value
    if isinstance(value, list):
        if len(value) > 256:
            raise ValueError("scenario_value_limit")
        return [_bounded_json_copy(item, budget, depth + 1) for item in value]
    if isinstance(value, Mapping):
        if len(value) > 128:
            raise ValueError("scenario_value_limit")
        copied: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 256:
                raise ValueError("scenario_value_limit")
            budget[1] += len(key)
            if budget[1] > 16384:
                raise ValueError("scenario_value_limit")
            copied[key] = _bounded_json_copy(item, budget, depth + 1)
        return copied
    raise ValueError("scenario_value_type")


@dataclass
class Job:
    id: int
    model: str
    tenant: str
    source: str
    priority: int
    execute: Callable[[], dict[str, Any]]
    background: bool = False
    created_at: float = field(default_factory=time.monotonic)
    created_wall: float = field(default_factory=time.time)
    done: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    caller_timed_out: bool = False
    dispatched_at: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0
    context: contextvars.Context = field(default_factory=contextvars.copy_context)
    trace_id: str = ""
    admission: dict[str, Any] = field(default_factory=dict)
    cancel_event: threading.Event | None = None
    deadline: float | None = None
    fairness_wait_ms: float = 0.0
    fairness_checked_at: float | None = None
    model_switch_receipt: dict[str, Any] | None = None


class QueueFullError(RuntimeError):
    def __init__(self, message: str, *, reason: str = "queue_limit", retryable: bool = True, admission: dict[str, Any] | None = None):
        self.admission = admission or {
            "state": "rejected", "reason": reason, "queue_age_ms": 0, "retryable": bool(retryable),
        }
        self.admission_state = str(self.admission["state"])
        self.retryable = bool(retryable)
        self.terminal = not self.retryable
        super().__init__(message)


class ModelUnavailableError(RuntimeError):
    def __init__(self, message: str, *, reason: str = "model_unavailable", retryable: bool = True):
        self.admission = {
            "state": "rejected", "reason": reason, "queue_age_ms": 0, "retryable": bool(retryable),
        }
        self.admission_state = "rejected"
        self.retryable = bool(retryable)
        self.terminal = not self.retryable
        super().__init__(message)


class SchedulerTimeoutError(TimeoutError):
    """Caller deadline expired while a scheduler job was still pending/running.

    The job is intentionally not force-cancelled once dispatched: the runtime
    request may own a socket or a model runner that cannot be safely interrupted
    from this thread.  Structured metadata lets the service return a safe,
    retryable response without pretending the work was cancelled.
    """

    def __init__(self, job: Job, state: str, wait_timeout: float):
        self.job_id = job.id
        self.state = state
        self.wait_timeout = max(0.0, float(wait_timeout))
        self.retryable = True
        self.terminal = False
        self.error_code = "scheduler_caller_timeout"
        super().__init__(f"job {job.id} did not finish before caller timeout ({state})")


class SchedulerCancelledError(InterruptedError):
    """Caller cancellation ended its wait before a scheduler job completed."""

    def __init__(self, job: Job, state: str):
        self.job = job
        self.job_id = job.id
        self.state = state
        self.error_code = "scheduler_caller_cancelled"
        super().__init__(f"job {job.id} was cancelled by its caller ({state})")


class AffinityScheduler:
    """Shared multi-tenant, model-affinity scheduler with idle-only background work.

    Interactive work always wins. Background/preprocessing jobs are dispatched only
    after an idle grace period and are considered when no foreground work is queued.
    Background work is deliberately split into small jobs by the preprocessor so a
    foreground request can take over between micro-steps.
    """

    def __init__(self, runtime: Any, config: dict[str, Any]):
        cfg = config["scheduler"]
        bg_cfg = config.get("preprocessing", {})
        self.config = config
        self.runtime = runtime
        self.model_policy = ModelExecutionPolicy(config)
        self.max_parallel = int(cfg.get("max_parallel", 1))
        self.max_queue = int(cfg.get("max_queue", 256))
        self.max_queued_per_tenant = int(cfg.get("max_queued_per_tenant", 64))
        self.max_inflight_per_tenant = int(cfg.get("max_inflight_per_tenant", self.max_parallel))
        self.batch_jobs = int(cfg.get("affinity_batch_jobs", 8))
        self.batch_seconds = float(cfg.get("affinity_batch_seconds", 75))
        self.max_other_wait = float(cfg.get("max_other_model_wait_seconds", 45))
        self.switch_cooldown = float(cfg.get("switch_cooldown_seconds", 1))
        self.switch_failure_cooldown = max(1.0, float(cfg.get("model_switch_failure_cooldown_seconds", 20.0)))
        resilience_cfg = config.get("resilience", {})
        configured_default_wait = max(0.05, float(resilience_cfg.get("scheduler_wait_timeout_seconds", config.get("server", {}).get("request_timeout_seconds", 210) + 15)))
        self.max_caller_wait_timeout = max(0.05, float(cfg.get("max_caller_wait_timeout_seconds", config.get("client", {}).get("max_request_timeout_seconds", 900))))
        self.default_caller_wait_timeout = min(configured_default_wait, self.max_caller_wait_timeout)
        self.unload_others = int(cfg.get("max_loaded_models", 1)) <= 1
        self.background_idle_grace = max(0.0, float(bg_cfg.get("idle_grace_seconds", 3.0)))
        self.background_switch_grace = max(self.background_idle_grace, float(bg_cfg.get("model_switch_idle_seconds", 10.0)))
        self.status_max_items = max(1, min(256, int(cfg.get("status_max_items", 64))))
        self.cache_stats_max_items = max(1, min(256, int(cfg.get("cache_stats_max_items", 32))))

        self._cond = threading.Condition()
        self._pending: list[Job] = []
        self._job_id = 0
        self._active_model: str | None = None
        self._active_since = 0.0
        self._active_dispatched = 0
        self._inflight = 0
        self._inflight_background = 0
        self._inflight_by_tenant: dict[str, int] = {}
        self._inflight_jobs: dict[int, Job] = {}
        self._tenant_vruntime: dict[str, int] = {}
        self._switch_sequence = 0
        self._last_switch = 0.0
        self._switching = False
        self._model_blocked_until: dict[str, float] = {}
        self._model_last_error: dict[str, str] = {}
        self._model_vram_bytes: dict[str, int] = {}
        self._running = True
        self._last_foreground_activity = time.monotonic()
        self._foreground_generation = 0
        self._foreground_preempt_hook: Callable[[], None] | None = None
        self._background_gpu_lease = False
        self._executor = ThreadPoolExecutor(max_workers=self.max_parallel, thread_name_prefix="local-ai")
        self._stats = {
            "submitted": 0,
            "completed": 0,
            "failed": 0,
            "model_switches": 0,
            "affinity_dispatches": 0,
            "evictions": 0,
            "queue_rejections": 0,
            "prewarms": 0,
            "caller_timeouts": 0,
            "cancelled_pending": 0,
            "switch_time_ms": 0.0,
            "background_submitted": 0,
            "background_dispatched": 0,
            "background_completed": 0,
            "background_failed": 0,
            "background_yields": 0,
            "background_gpu_lease_rejections": 0,
            "model_switch_failures": 0,
            "model_fast_rejections": 0,
        }

        try:
            # Do not blindly trust a model loaded by another Ollama client. A runner
            # with a tiny default context must pass through prepare_model() before it
            # becomes the scheduler's active profile.
            details = runtime.loaded_model_details() if hasattr(runtime, "loaded_model_details") else []
            for row in details:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("name", row.get("model", "")) or "").strip()
                vram_bytes = row.get("vram_bytes")
                if (
                    name
                    and isinstance(vram_bytes, (int, float))
                    and not isinstance(vram_bytes, bool)
                    and math.isfinite(vram_bytes)
                    and vram_bytes > 0
                ):
                    model_key = name.casefold()
                    self._model_vram_bytes[model_key] = self._model_vram_bytes.get(model_key, 0) + int(
                        round(float(vram_bytes))
                    )
            for row in details:
                name = str(row.get("name", "")) if isinstance(row, dict) else ""
                ctx = int(row.get("context_length", 0) or 0) if isinstance(row, dict) else 0
                if name and ctx >= self.model_policy.profile(name).num_ctx:
                    self._active_model = name
                    self._active_since = time.monotonic()
                    break
        except Exception:
            pass

        self._dispatcher = threading.Thread(target=self._dispatch_loop, name="local-ai-dispatcher", daemon=True)
        self._dispatcher.start()

    def run_benchmark_scenario(
        self,
        *,
        name: str,
        contract: Mapping[str, Any],
        resource_sampler: Any | None = None,
    ) -> dict[str, Any]:
        """Expose only validated measurements from a runtime scenario executor.

        The runtime owns scenario execution and receipt provenance. This adapter
        never treats input contract values as observations or creates receipts.
        """
        if not isinstance(name, str) or name not in _T12_SCENARIO_NAMES:
            return {"success": False, "error_type": "unsupported_scenario"}
        if not isinstance(contract, Mapping):
            return {"success": False, "error_type": "invalid_scenario_contract"}

        try:
            if len(contract) > 32:
                return {"success": False, "error_type": "invalid_scenario_contract"}
            safe_contract: dict[str, Any] = {}
            contract_budget = [0, 0]
            for key, value in contract.items():
                if not isinstance(key, str) or not key or len(key) > 128:
                    return {"success": False, "error_type": "invalid_scenario_contract"}
                if key.casefold() in _T12_FIXTURE_CONTRACT_FIELDS:
                    return {"success": False, "error_type": "invalid_scenario_contract"}
                safe_contract[key] = _bounded_json_copy(value, contract_budget)
        except Exception:
            return {"success": False, "error_type": "invalid_scenario_contract"}

        if safe_contract.get("scenario") != name:
            return {"success": False, "error_type": "invalid_scenario_contract"}
        required_fields = safe_contract.get("required_fields")
        if (
            not isinstance(required_fields, list)
            or not required_fields
            or len(required_fields) > 64
            or any(
                not isinstance(field, str)
                or not field
                or len(field) > 128
                or field in _T12_RESERVED_FIELDS
                for field in required_fields
            )
            or len(set(required_fields)) != len(required_fields)
        ):
            return {"success": False, "error_type": "invalid_scenario_contract"}
        requested_fields = tuple(required_fields)

        execute_scenario = getattr(self.runtime, "run_benchmark_scenario", None)
        if not callable(execute_scenario):
            return {"success": False, "error_type": "scenario_executor_unavailable"}

        try:
            execute_args: dict[str, Any] = {"name": name, "contract": safe_contract, "scheduler": self}
            if callable(getattr(resource_sampler, "sample_vram", None)):
                execute_args["resource_sampler"] = resource_sampler
            result = execute_scenario(**execute_args)
        except Exception as exc:
            return {"success": False, "error_type": type(exc).__name__}
        if not isinstance(result, Mapping):
            return {"success": False, "error_type": "scenario_execution_failed"}
        try:
            if result.get("scenario") == name and result.get("status") == "unmeasured":
                missing_fields = result.get("missing_fields")
                safe_missing = [
                    field for field in missing_fields
                    if isinstance(field, str) and field and len(field) <= 128
                ] if isinstance(missing_fields, list) else []
                return {
                    "success": False,
                    "error_type": "scenario_measurement_missing",
                    "missing_fields": sorted(set(safe_missing)),
                }
            if (
                result.get("success", True) is not True
                or result.get("scenario") != name
                or result.get("status") != "measured"
            ):
                return {"success": False, "error_type": "scenario_result_invalid"}
            metrics = result.get("metrics")
            if not isinstance(metrics, Mapping) or len(metrics) > 256:
                return {"success": False, "error_type": "scenario_result_invalid"}
            if any(not isinstance(field, str) for field in metrics):
                return {"success": False, "error_type": "scenario_result_invalid"}
            receipt_id = result.get("receipt_id")
            if not isinstance(receipt_id, str) or not receipt_id.strip() or len(receipt_id) > 256:
                return {"success": False, "error_type": "scenario_receipt_unavailable"}

            report: dict[str, Any] = {"success": True}
            metric_budget = [0, 0]
            missing_metrics: list[str] = []
            for field in requested_fields:
                if field not in metrics or metrics[field] is None:
                    missing_metrics.append(field)
                    continue
                report[field] = _bounded_json_copy(metrics[field], metric_budget)
            if missing_metrics:
                return {
                    "success": False,
                    "error_type": "scenario_measurement_missing",
                    "missing_fields": missing_metrics,
                }
            report["receipt_id"] = receipt_id.strip()
            return report
        except Exception:
            return {"success": False, "error_type": "scenario_result_invalid"}

    def _resource_status(self) -> dict[str, Any]:
        candidates = [
            getattr(self.runtime, "resource_status", None),
            getattr(self.runtime, "vram_status", None),
            getattr(getattr(self.runtime, "vram_balancer", None), "status", None),
            getattr(getattr(self.runtime, "resource_monitor", None), "status", None),
        ]
        for candidate in candidates:
            if not callable(candidate):
                continue
            try:
                value = candidate()
            except Exception:
                continue
            if isinstance(value, dict):
                return value
        configured = self.config.get("resource_pressure", self.config.get("scheduler", {}).get("resource_pressure", {}))
        return dict(configured) if isinstance(configured, dict) else {}

    def _observe_model_vram_bytes(
        self,
        model: str,
        *,
        should_stop: Callable[[], bool] | None = None,
        deadline: float | None = None,
    ) -> int | None:
        model_key = str(model or "").strip().casefold()
        provider = getattr(self.runtime, "loaded_model_details", None)
        if not model_key or not callable(provider):
            return None
        try:
            rows = provider(force_refresh=True, should_stop=should_stop, deadline=deadline)
        except TypeError:
            try:
                rows = provider(should_stop=should_stop, deadline=deadline)
            except TypeError:
                try:
                    rows = provider()
                except Exception:
                    return None
            except Exception:
                return None
        except Exception:
            return None
        if not isinstance(rows, list):
            return None
        matching_sizes = [
            int(round(float(row["vram_bytes"])))
            for row in rows
            if isinstance(row, dict)
            and str(row.get("name", row.get("model", ""))).strip().casefold() == model_key
            and isinstance(row.get("vram_bytes"), (int, float))
            and not isinstance(row.get("vram_bytes"), bool)
            and math.isfinite(row["vram_bytes"])
            and row["vram_bytes"] > 0
        ]
        return sum(matching_sizes) if matching_sizes else None

    def _configured_model_vram_estimate(self, model_key: str) -> int | None:
        config = getattr(self, "config", {})
        scheduler_config = config.get("scheduler", {}) if isinstance(config, dict) else {}
        estimates = scheduler_config.get("model_vram_estimates_bytes", {}) if isinstance(scheduler_config, dict) else {}
        if not isinstance(estimates, dict):
            return None
        for model, value in estimates.items():
            if (
                str(model or "").strip().casefold() == model_key
                and isinstance(value, int)
                and not isinstance(value, bool)
                and value > 0
            ):
                return value
        return None

    def _supports_post_unload_admission(self, model: str) -> bool:
        runtime = getattr(self, "runtime", None)
        capability = getattr(runtime, "supports_post_unload_admission", None)
        if not callable(capability):
            return False
        live_resource_providers = (
            getattr(runtime, "resource_status", None),
            getattr(runtime, "vram_status", None),
            getattr(getattr(runtime, "vram_balancer", None), "status", None),
            getattr(getattr(runtime, "resource_monitor", None), "status", None),
        )
        if not any(callable(provider) for provider in live_resource_providers):
            return False
        try:
            return bool(capability(model))
        except Exception:
            return False

    def _post_unload_vram_admission(self, model: str) -> dict[str, Any]:
        resource = self._resource_status()
        total_mb = resource.get("vram_total_mb")
        available_mb = resource.get("vram_available_mb")
        valid_total = (
            isinstance(total_mb, (int, float)) and not isinstance(total_mb, bool)
            and math.isfinite(total_mb) and total_mb > 0
        )
        valid_available = (
            isinstance(available_mb, (int, float)) and not isinstance(available_mb, bool)
            and math.isfinite(available_mb) and available_mb >= 0
        )
        model_key = str(model or "").strip().casefold()
        estimate_map = getattr(self, "_model_vram_bytes", {})
        measured = estimate_map.get(model_key) if isinstance(estimate_map, dict) else None
        if not isinstance(measured, int) or isinstance(measured, bool) or measured <= 0:
            measured = None
        configured = self._configured_model_vram_estimate(model_key)
        required_values = [value for value in (measured, configured) if value is not None]
        required = max(required_values) if required_values else None
        estimate_source = (
            "measured_and_configured" if measured is not None and configured is not None
            else "configured" if configured is not None
            else "measured" if measured is not None
            else "unknown"
        )
        if not valid_total or not valid_available:
            return {
                "state": "rejected", "reason": "post_unload_vram_unavailable",
                "vram_admission": "rejected", "vram_admission_phase": "post_unload",
                "vram_estimate_source": estimate_source,
            }
        total_bytes = int(round(float(total_mb) * 1024 * 1024))
        available_bytes = int(round(min(float(total_mb), float(available_mb)) * 1024 * 1024))
        result: dict[str, Any] = {
            "state": "rejected", "reason": "target_vram_estimate_unavailable",
            "vram_admission": "rejected", "vram_admission_phase": "post_unload",
            "vram_budget_bytes": total_bytes, "vram_available_bytes": available_bytes,
            "vram_admission_budget_bytes": available_bytes,
            "vram_estimate_source": estimate_source,
        }
        if required is None:
            return result
        result["vram_required_bytes"] = required
        result["vram_incremental_required_bytes"] = required
        if available_bytes >= required:
            result.update(state="admitted", reason="capacity_available_after_unload", vram_admission="admitted")
        else:
            result["reason"] = "vram_budget_after_unload"
        return result

    def _admission(self, *, background: bool, model: str | None = None) -> dict[str, Any]:
        resource = self._resource_status()
        pressure = str(resource.get("pressure_level", "nominal") or "nominal").lower()
        vram_fields: dict[str, int] = {}
        total_mb = resource.get("vram_total_mb")
        available_mb = resource.get("vram_available_mb")
        if (
            isinstance(total_mb, (int, float)) and not isinstance(total_mb, bool)
            and math.isfinite(total_mb) and total_mb > 0
            and isinstance(available_mb, (int, float)) and not isinstance(available_mb, bool)
            and math.isfinite(available_mb) and available_mb >= 0
        ):
            vram_fields = {
                "vram_budget_bytes": int(round(float(total_mb) * 1024 * 1024)),
                "vram_available_bytes": int(round(min(float(total_mb), float(available_mb)) * 1024 * 1024)),
            }
        model_key = str(model or "").strip().casefold()
        active_key = str(getattr(self, "_active_model", None) or "").strip().casefold()
        can_defer_switch = bool(
            model_key and active_key and active_key != model_key
            and bool(getattr(self, "unload_others", False))
            and self._supports_post_unload_admission(model or "")
        )
        estimates = getattr(self, "_model_vram_bytes", {})
        incremental_required: int | None = None
        admission_budget: int | None = None
        vram_admission_state: str | None = None
        vram_estimate_source = "unknown"
        if vram_fields:
            reclaimable = 0
            if (
                bool(getattr(self, "unload_others", False))
                and active_key
                and active_key != model_key
                and isinstance(estimates, dict)
            ):
                active_size = estimates.get(active_key)
                if isinstance(active_size, int) and not isinstance(active_size, bool) and active_size > 0:
                    # Configured sizes are upper bounds, not observed bytes that
                    # unloading is guaranteed to return to the device.
                    reclaimable = active_size
            admission_budget = min(
                vram_fields["vram_budget_bytes"],
                vram_fields["vram_available_bytes"] + reclaimable,
            )
            if model_key == active_key and model_key:
                incremental_required = 0
                vram_estimate_source = "resident"
            elif isinstance(estimates, dict):
                estimate = estimates.get(model_key)
                if isinstance(estimate, int) and not isinstance(estimate, bool) and estimate > 0:
                    incremental_required = estimate
                    vram_estimate_source = "measured"
            if incremental_required is None:
                configured_estimate = self._configured_model_vram_estimate(model_key)
                if configured_estimate is not None:
                    incremental_required = configured_estimate
                    vram_estimate_source = "configured"
            vram_fields["vram_admission_budget_bytes"] = admission_budget
            if incremental_required is None:
                vram_admission_state = "deferred" if can_defer_switch else "unknown"
            else:
                vram_fields["vram_incremental_required_bytes"] = incremental_required
                if incremental_required <= admission_budget:
                    vram_admission_state = "admitted"
                else:
                    vram_admission_state = "deferred" if can_defer_switch else "rejected"
        factor = resource.get("context_budget_factor", 1.0)
        try:
            factor = max(0.0, min(1.0, float(factor)))
        except (TypeError, ValueError, OverflowError):
            factor = 1.0
        throttled = bool(resource.get("throttle_background", False))
        pressure_rejected = background and throttled and pressure in {"high", "critical"}
        budget_rejected = bool(vram_fields) and (
            vram_admission_state == "rejected"
            or (
                vram_fields["vram_available_bytes"] <= 0
                and (incremental_required is None or incremental_required > 0)
                and not can_defer_switch
            )
        )
        if pressure_rejected or budget_rejected:
            result = {
                "state": "rejected", "reason": "resource_pressure", "pressure_level": pressure,
                "context_budget_factor": factor, "queue_age_ms": 0, "retryable": True,
                **vram_fields,
            }
            if vram_fields:
                result["vram_admission"] = "rejected"
            result["vram_estimate_source"] = vram_estimate_source
            if budget_rejected:
                result["reason"] = "vram_budget"
            return result
        if vram_admission_state == "deferred":
            result = {
                "state": "degraded", "reason": "vram_admission_deferred_until_unload",
                "pressure_level": pressure, "context_budget_factor": factor,
                "queue_age_ms": 0, "retryable": True, **vram_fields,
            }
            result["vram_admission"] = "deferred"
            result["vram_estimate_source"] = vram_estimate_source
            return result
        degraded = pressure in {"moderate", "high", "critical"} or factor < 1.0
        result = {
            "state": "degraded" if degraded else "accepted",
            "reason": "resource_pressure" if degraded else "capacity_available",
            "pressure_level": pressure, "context_budget_factor": factor,
            "queue_age_ms": 0, "retryable": False,
            **vram_fields,
        }
        if vram_fields:
            result["vram_admission"] = vram_admission_state or "unknown"
        result["vram_estimate_source"] = vram_estimate_source
        return result

    @staticmethod
    def _bounded_mapping(value: Any, limit: int) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {"items": {}, "truncated": False, "total": 0, "limit": limit}
        items = dict(sorted(value.items(), key=lambda item: str(item[0]))[:limit])
        return {"items": items, "truncated": len(value) > limit, "total": len(value), "limit": limit}

    def _cache_stats(self) -> dict[str, Any]:
        provider = getattr(self.runtime, "cache_stats", None)
        if not callable(provider):
            return self._bounded_mapping({}, self.cache_stats_max_items)
        try:
            return self._bounded_mapping(provider(), self.cache_stats_max_items)
        except Exception:
            return {"items": {}, "truncated": False, "total": 0, "limit": self.cache_stats_max_items, "degraded": True}

    def submit(
        self,
        model: str,
        tenant: str,
        source: str,
        execute: Callable[[], dict[str, Any]],
        priority: int = 5,
        wait_timeout: float | None = None,
        *,
        background: bool = False,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        tenant = tenant or "default"
        priority = max(0, min(int(priority), 9))
        # Never let an omitted/accidentally huge caller timeout turn a stuck runtime
        # into a permanently occupied HTTP/MCP handler. Explicit shorter deadlines
        # are preserved; longer ones are capped by one configurable hard ceiling.
        effective_wait_timeout = self.default_caller_wait_timeout if wait_timeout is None else max(0.05, float(wait_timeout))
        effective_wait_timeout = min(effective_wait_timeout, self.max_caller_wait_timeout)
        request_deadline = time.monotonic() + effective_wait_timeout
        if background:
            # Background work cannot smuggle itself above foreground work through a
            # caller-supplied priority.
            priority = min(priority, 1)
        preempt_hook: Callable[[], None] | None = None
        with self._cond:
            now = time.monotonic()
            blocked_until = self._model_blocked_until.get(model, 0.0)
            if blocked_until > now:
                self._stats["model_fast_rejections"] += 1
                remaining = max(1, int(blocked_until - now + 0.999))
                detail = self._model_last_error.get(model, "model preparation failed")
                raise ModelUnavailableError(f"model {model!r} temporarily unavailable ({detail}); retry after ~{remaining}s")
            if blocked_until:
                self._model_blocked_until.pop(model, None)
                self._model_last_error.pop(model, None)
            tenant_queued = sum(1 for job in self._pending if job.tenant == tenant)
            admission = self._admission(background=background, model=model)
            if admission["state"] == "rejected":
                self._stats["queue_rejections"] += 1
                raise QueueFullError("resource pressure blocks background admission", reason="resource_pressure", admission=admission)
            if len(self._pending) >= self.max_queue or tenant_queued >= self.max_queued_per_tenant:
                self._stats["queue_rejections"] += 1
                admission = {"state": "rejected", "reason": "queue_limit", "queue_age_ms": 0, "retryable": True}
                raise QueueFullError(f"queue limit reached for tenant {tenant!r}", admission=admission)
            self._job_id += 1
            trace_observer = observer()
            trace_id = str(getattr(trace_observer, "trace_id", "") or "")
            job = Job(
                self._job_id, model, tenant, source, priority, execute,
                background=background, trace_id=trace_id, admission=admission,
                cancel_event=cancel_event, deadline=request_deadline,
            )
            self._pending.append(job)
            if trace_observer is not None and trace_id:
                try:
                    trace_observer.store.link(trace_id, scheduler_job_id=str(job.id))
                    trace_observer.event("scheduled", {"scheduler_job_id": job.id, "model": model, "background": background})
                except Exception:
                    pass
            self._stats["submitted"] += 1
            if background:
                self._stats["background_submitted"] += 1
            else:
                # Mark foreground intent before notifying the dispatcher. This closes
                # the race where an idle GPU worker could acquire the GPU between a
                # user request arriving and the foreground model beginning to load.
                self._last_foreground_activity = time.monotonic()
                self._foreground_generation += 1
                preempt_hook = self._foreground_preempt_hook

        # Local AI background GPU work runs on a separate Ollama endpoint and is disposable.
        # Stop it synchronously before the foreground dispatcher is allowed to load a
        # foreground runner, preventing transient dual-runner VRAM pressure/offload.
        if preempt_hook is not None:
            try:
                preempt_hook()
            except Exception:
                pass
        with self._cond:
            if not background:
                self._background_gpu_lease = False
            self._cond.notify_all()

        deadline = request_deadline
        while not job.done.is_set():
            remaining = max(0.0, deadline - time.monotonic())
            wait_slice = min(0.05, remaining) if cancel_event is not None else remaining
            if job.done.wait(wait_slice):
                break

            if cancel_event is not None and cancel_event.is_set():
                with self._cond:
                    if job.done.is_set():
                        break
                    state = "running" if job.started_at else "dispatching"
                    if job in self._pending:
                        self._pending.remove(job)
                        self._stats["cancelled_pending"] += 1
                        job.error = "caller cancelled before dispatch"
                        job.finished_at = time.monotonic()
                        job.done.set()
                        state = "pending"
                        self._cond.notify_all()
                raise SchedulerCancelledError(job, state)

            if time.monotonic() >= deadline:
                with self._cond:
                    if job.done.is_set():
                        break
                    job.caller_timed_out = True
                    self._stats["caller_timeouts"] += 1
                    if job.cancel_event is not None:
                        job.cancel_event.set()
                    state = "running" if job.started_at else "dispatching"
                    if job in self._pending:
                        self._pending.remove(job)
                        self._stats["cancelled_pending"] += 1
                        job.error = "caller timed out before dispatch"
                        job.finished_at = time.monotonic()
                        job.done.set()
                        state = "pending"
                        self._cond.notify_all()
                raise SchedulerTimeoutError(job, state, effective_wait_timeout)
        queue_wait_ms = max(0.0, ((job.started_at or job.finished_at or time.monotonic()) - job.created_at) * 1000)
        service_ms = max(0.0, (job.finished_at - job.started_at) * 1000) if job.finished_at and job.started_at else 0.0
        if job.error:
            admission = dict(job.admission)
            admission["queue_age_ms"] = round(queue_wait_ms, 1)
            admission["fairness_wait_ms"] = round(job.fairness_wait_ms, 1)
            result = {
                "success": False,
                "error": job.error,
                "job_id": job.id,
                "admission": admission,
                "admission_state": admission["state"],
                "_lah_scheduler_queue_wait_ms": queue_wait_ms,
                "_lah_scheduler_service_ms": service_ms,
                "_lah_scheduler_fairness_wait_ms": round(job.fairness_wait_ms, 1),
                "_lah_scheduler_background": job.background,
            }
            if job.model_switch_receipt is not None:
                result["_lah_scheduler_model_switch"] = dict(job.model_switch_receipt)
            return result
        if isinstance(job.result, dict):
            job.result.setdefault("job_id", job.id)
            admission = dict(job.admission)
            admission["queue_age_ms"] = round(queue_wait_ms, 1)
            admission["fairness_wait_ms"] = round(job.fairness_wait_ms, 1)
            job.result.setdefault("admission", admission)
            job.result.setdefault("admission_state", admission["state"])
            job.result.setdefault("_lah_scheduler_queue_wait_ms", queue_wait_ms)
            job.result.setdefault("_lah_scheduler_service_ms", service_ms)
            job.result.setdefault("_lah_scheduler_fairness_wait_ms", round(job.fairness_wait_ms, 1))
            if job.model_switch_receipt is not None:
                job.result.setdefault("_lah_scheduler_model_switch", dict(job.model_switch_receipt))
            job.result.setdefault("_lah_scheduler_background", job.background)
        return job.result

    def enqueue(
        self,
        model: str,
        tenant: str,
        source: str,
        execute: Callable[[], dict[str, Any]],
        priority: int = 1,
        *,
        background: bool = True,
    ) -> Job:
        """Queue work without binding its lifecycle to a caller timeout."""
        tenant = tenant or "default"
        priority = max(0, min(int(priority), 9))
        if background:
            priority = min(priority, 1)
        with self._cond:
            now = time.monotonic()
            blocked_until = self._model_blocked_until.get(model, 0.0)
            if blocked_until > now:
                self._stats["model_fast_rejections"] += 1
                remaining = max(1, int(blocked_until - now + 0.999))
                detail = self._model_last_error.get(model, "model preparation failed")
                raise ModelUnavailableError(f"model {model!r} temporarily unavailable ({detail}); retry after ~{remaining}s")
            tenant_queued = sum(1 for job in self._pending if job.tenant == tenant)
            admission = self._admission(background=background)
            if admission["state"] == "rejected":
                self._stats["queue_rejections"] += 1
                raise QueueFullError("resource pressure blocks background admission", reason="resource_pressure", admission=admission)
            if len(self._pending) >= self.max_queue or tenant_queued >= self.max_queued_per_tenant:
                self._stats["queue_rejections"] += 1
                admission = {"state": "rejected", "reason": "queue_limit", "queue_age_ms": 0, "retryable": True}
                raise QueueFullError(f"queue limit reached for tenant {tenant!r}", admission=admission)
            self._job_id += 1
            trace_observer = observer()
            trace_id = str(getattr(trace_observer, "trace_id", "") or "")
            job = Job(self._job_id, model, tenant, source, priority, execute, background=background, trace_id=trace_id, admission=admission)
            self._pending.append(job)
            if trace_observer is not None and trace_id:
                try:
                    trace_observer.store.link(trace_id, scheduler_job_id=str(job.id))
                    trace_observer.event("scheduled", {"scheduler_job_id": job.id, "model": model, "background": background})
                except Exception:
                    pass
            self._stats["submitted"] += 1
            if background:
                self._stats["background_submitted"] += 1
            self._cond.notify_all()
            return job

    def set_foreground_preempt_hook(self, hook: Callable[[], None] | None) -> None:
        with self._cond:
            self._foreground_preempt_hook = hook

    def foreground_idle_seconds(self) -> float:
        with self._cond:
            return max(0.0, time.monotonic() - self._last_foreground_activity)

    def acquire_background_gpu(self, min_idle_seconds: float) -> bool:
        """Atomically lend the single GPU to Local AI's disposable background runtime.

        Foreground intent always wins. The active foreground runner is unloaded before
        the lease is granted so the secondary Ollama server never intentionally shares
        constrained accelerator memory with the foreground runner.
        """
        with self._cond:
            now = time.monotonic()
            if self._background_gpu_lease:
                return True
            if self._switching or self._inflight or self._pending:
                return False
            if now - self._last_foreground_activity < max(0.0, float(min_idle_seconds)):
                return False
            active = self._active_model
            self._switching = True
        foreign_loaded = False
        try:
            try:
                loaded = [str(x) for x in self.runtime.loaded_models()]
            except Exception:
                loaded = []
            known_models = set(str(v) for v in self.config.get("models", {}).values() if v)
            foreign_loaded = any(m and m not in known_models and m != active for m in loaded)
            if not foreign_loaded:
                for m in loaded:
                    if m:
                        try:
                            self.runtime.unload(m)
                        except Exception:
                            pass
        finally:
            with self._cond:
                # Re-check foreground activity because unloading happens outside the
                # scheduler lock. A request that arrived meanwhile invalidates lease.
                now = time.monotonic()
                clean = (
                    not foreign_loaded and not self._pending and self._inflight == 0
                    and now - self._last_foreground_activity >= max(0.0, float(min_idle_seconds))
                )
                if clean:
                    self._active_model = None
                    self._active_since = 0.0
                    self._active_dispatched = 0
                    self._background_gpu_lease = True
                elif foreign_loaded:
                    self._stats["background_gpu_lease_rejections"] += 1
                self._switching = False
                self._cond.notify_all()
                return bool(clean)

    def release_background_gpu(self) -> None:
        with self._cond:
            self._background_gpu_lease = False
            self._cond.notify_all()

    def foreground_pending(self) -> bool:
        with self._cond:
            return any(not j.background for j in self._pending)

    def foreground_busy(self) -> bool:
        """True when background work should yield before starting another micro-step."""
        with self._cond:
            foreground_inflight = self._inflight - self._inflight_background
            return bool(foreground_inflight > 0 or any(not j.background for j in self._pending) or self._switching)

    def background_allowed(self, *, require_switch_idle: bool = False) -> bool:
        with self._cond:
            now = time.monotonic()
            if self._inflight - self._inflight_background > 0 or any(not j.background for j in self._pending):
                return False
            grace = self.background_switch_grace if require_switch_idle else self.background_idle_grace
            return now - self._last_foreground_activity >= grace

    def foreground_generation(self) -> int:
        with self._cond:
            return self._foreground_generation

    def note_background_yield(self) -> None:
        with self._cond:
            self._stats["background_yields"] += 1

    def _foreground_pending_jobs(self) -> list[Job]:
        return [j for j in self._pending if not j.background]

    def _background_pending_jobs(self) -> list[Job]:
        return [j for j in self._pending if j.background]

    def _eligible_jobs(self, now: float) -> list[Job]:
        foreground = self._foreground_pending_jobs()
        if foreground:
            return foreground
        if now - self._last_foreground_activity < self.background_idle_grace:
            return []
        return self._background_pending_jobs()

    def _dispatch_loop(self) -> None:
        while self._running:
            target_switch: str | None = None
            selected: Job | None = None
            with self._cond:
                while self._running:
                    now = time.monotonic()
                    if self._background_gpu_lease:
                        self._cond.wait(timeout=0.10)
                        continue
                    eligible = self._eligible_jobs(now)
                    if eligible and self._active_model is None and self._inflight == 0:
                        target_switch = self._choose_initial_model(eligible, now)
                        if target_switch:
                            self._switching = True
                            break

                    if eligible and self._active_model is not None:
                        if self._should_switch(now, eligible):
                            if self._inflight == 0:
                                target_switch = self._choose_next_model(eligible, exclude=self._active_model, now=now)
                                if target_switch:
                                    self._switching = True
                                    break
                        elif self._inflight < self._active_parallel_limit():
                            selected = self._choose_job_for_active_model(now, eligible)
                            if selected is not None:
                                self._pending.remove(selected)
                                selected.dispatched_at = time.monotonic()
                                self._inflight += 1
                                self._inflight_jobs[selected.id] = selected
                                if selected.background:
                                    self._inflight_background += 1
                                    self._stats["background_dispatched"] += 1
                                self._inflight_by_tenant[selected.tenant] = self._inflight_by_tenant.get(selected.tenant, 0) + 1
                                self._tenant_vruntime[selected.tenant] = self._tenant_vruntime.get(selected.tenant, 0) + 1
                                self._active_dispatched += 1
                                self._stats["affinity_dispatches"] += 1
                                break

                    self._cond.wait(timeout=0.15)

            if not self._running:
                break

            if target_switch:
                self._perform_switch(
                    target_switch,
                    should_stop=lambda target=target_switch: not self._has_active_preparation_waiter(target),
                )
                continue

            if selected is not None:
                try:
                    self._executor.submit(self._run_job, selected)
                except Exception as exc:
                    with self._cond:
                        self._inflight = max(0, self._inflight - 1)
                        self._inflight_jobs.pop(selected.id, None)
                        if selected.background:
                            self._inflight_background = max(0, self._inflight_background - 1)
                        self._active_dispatched = max(0, self._active_dispatched - 1)
                        current = self._inflight_by_tenant.get(selected.tenant, 1) - 1
                        if current <= 0:
                            self._inflight_by_tenant.pop(selected.tenant, None)
                        else:
                            self._inflight_by_tenant[selected.tenant] = current
                        selected.error = f"dispatch failed: {exc}"
                        selected.done.set()
                        self._cond.notify_all()

    def _active_parallel_limit(self) -> int:
        if not self._active_model:
            return self.max_parallel
        return max(1, min(self.max_parallel, self.model_policy.parallel_limit(self._active_model)))

    def _choose_initial_model(self, jobs: list[Job], now: float) -> str | None:
        loaded = set()
        try:
            loaded = set(self.runtime.loaded_models())
        except Exception:
            pass
        ordered = sorted(jobs, key=lambda j: (-j.priority, j.created_at))
        for job in ordered:
            if job.model in loaded:
                return job.model
        candidate = ordered[0] if ordered else None
        if candidate and candidate.background and now - self._last_foreground_activity < self.background_switch_grace:
            return None
        return candidate.model if candidate else None

    @staticmethod
    def _models_waiting_from(jobs: list[Job], exclude: str | None = None) -> list[str]:
        seen: set[str] = set()
        models: list[str] = []
        for job in sorted(jobs, key=lambda j: j.created_at):
            if job.model == exclude or job.model in seen:
                continue
            seen.add(job.model)
            models.append(job.model)
        return models

    def _oldest_wait_for_other_model(self, now: float, jobs: list[Job]) -> float:
        waits = [now - j.created_at for j in jobs if j.model != self._active_model]
        return max(waits, default=0.0)

    def _has_active_pending(self, jobs: list[Job]) -> bool:
        return any(j.model == self._active_model for j in jobs)

    def _should_switch(self, now: float, jobs: list[Job]) -> bool:
        if not self._models_waiting_from(jobs, exclude=self._active_model):
            return False
        if now - self._last_switch < self.switch_cooldown:
            return False
        # Background jobs may only cause a model swap after a longer idle window.
        if jobs and all(j.background for j in jobs) and now - self._last_foreground_activity < self.background_switch_grace:
            return False
        if not self._has_active_pending(jobs):
            return True
        if self.batch_jobs > 0 and self._active_dispatched >= self.batch_jobs:
            return True
        if self.batch_seconds > 0 and self._active_since and now - self._active_since >= self.batch_seconds:
            return True
        # Anti-starvation is for real requests; background jobs must never force a
        # switch merely because they have been waiting for a long time.
        foreground_jobs = [j for j in jobs if not j.background]
        if foreground_jobs and self.max_other_wait > 0 and self._oldest_wait_for_other_model(now, foreground_jobs) >= self.max_other_wait:
            return True
        return False

    def _choose_next_model(self, jobs: list[Job], exclude: str | None, now: float) -> str | None:
        candidates = [j for j in jobs if j.model != exclude]
        if not candidates:
            return None
        foreground = [j for j in candidates if not j.background]
        if foreground:
            candidates = foreground
            if self.max_other_wait > 0:
                starving = [j for j in candidates if now - j.created_at >= self.max_other_wait]
                if starving:
                    return min(starving, key=lambda j: j.created_at).model
        elif now - self._last_foreground_activity < self.background_switch_grace:
            return None

        groups: dict[str, list[Job]] = {}
        for job in candidates:
            groups.setdefault(job.model, []).append(job)

        def score(item: tuple[str, list[Job]]) -> tuple[float, float, float]:
            _model, grouped = item
            count = len(grouped)
            max_priority = max(j.priority for j in grouped)
            oldest = min(j.created_at for j in grouped)
            return (-(count * 2 + max_priority), oldest, -count)

        return min(groups.items(), key=score)[0]

    def _choose_job_for_active_model(self, now: float, jobs: list[Job]) -> Job | None:
        candidates = [
            j for j in jobs
            if j.model == self._active_model
            and self._inflight_by_tenant.get(j.tenant, 0) < self.max_inflight_per_tenant
        ]
        if not candidates:
            return None
        foreground = [j for j in candidates if not j.background]
        if foreground:
            candidates = foreground
        elif not self.background_allowed(require_switch_idle=False):
            return None

        def effective_priority(job: Job) -> int:
            wait = now - job.created_at
            # Let an old foreground request catch up with higher-priority arrivals.
            # Cap at the public priority ceiling so tenant virtual runtime can still
            # share capacity fairly once waiting jobs have aged into the same tier.
            return min(9, job.priority + int(wait // 30.0)) if not job.background else job.priority

        def score(job: Job) -> tuple[float, int, float]:
            priority = effective_priority(job)
            vruntime = self._tenant_vruntime.get(job.tenant, 0)
            return (-priority, vruntime, job.created_at)

        selected = min(candidates, key=score)
        selected_priority = effective_priority(selected)
        for job in candidates:
            if (
                job is not selected
                and job.tenant != selected.tenant
                and effective_priority(job) == selected_priority
                and job.fairness_checked_at is not None
            ):
                job.fairness_wait_ms += max(0.0, now - job.fairness_checked_at) * 1000
            job.fairness_checked_at = now
        return selected

    def _has_active_preparation_waiter(self, target: str) -> bool:
        now = time.monotonic()
        with self._cond:
            return any(
                job.model == target
                and not job.done.is_set()
                and (job.cancel_event is None or not job.cancel_event.is_set())
                and (job.deadline is None or now < job.deadline)
                for job in self._pending
            )

    def _perform_switch(
        self,
        target: str,
        *,
        should_stop: Callable[[], bool] | None = None,
        deadline: float | None = None,
    ) -> bool:
        evicted: list[str] = []
        vram_before_bytes: int | None = None
        observed_vram_bytes: int | None = None
        started = time.perf_counter()
        prepare_duration_ms = 0.0
        error = ""
        cancelled = False
        admission_rejected = False
        post_unload_admission: dict[str, Any] | None = None
        if should_stop is not None and should_stop():
            cancelled = True
        else:
            try:
                vram_before_bytes = self._observe_model_vram_bytes(
                    target,
                    should_stop=should_stop,
                    deadline=deadline,
                )
                prepare_kwargs: dict[str, Any] = {"unload_others": self.unload_others}
                active_model = str(getattr(self, "_active_model", None) or "").strip()
                if (
                    bool(getattr(self, "unload_others", False))
                    and active_model
                    and active_model.casefold() != target.strip().casefold()
                    and self._supports_post_unload_admission(target)
                ):
                    def check_post_unload_admission() -> dict[str, Any]:
                        nonlocal post_unload_admission
                        post_unload_admission = self._post_unload_vram_admission(target)
                        return post_unload_admission

                    prepare_kwargs["post_unload_admission"] = check_post_unload_admission
                if should_stop is not None or deadline is not None:
                    prepare_kwargs.update(should_stop=should_stop, deadline=deadline)
                prepare_started = time.perf_counter()
                try:
                    prepared = self.runtime.prepare_model(target, **prepare_kwargs)
                finally:
                    prepare_duration_ms = (time.perf_counter() - prepare_started) * 1000
                # Runtime adapters historically returned either a list of evicted models
                # or None. Treat a falsey/non-list success value as no evictions instead
                # of letting an adapter quirk kill the dispatcher thread.
                evicted = list(prepared) if isinstance(prepared, (list, tuple, set)) else []
            except Exception as exc:
                admission = getattr(exc, "admission", None)
                if isinstance(admission, dict) and admission.get("state") == "rejected":
                    admission_rejected = True
                    post_unload_admission = dict(admission)
                    evicted_models = getattr(exc, "evicted_models", None)
                    evicted = list(evicted_models) if isinstance(evicted_models, (list, tuple, set)) else []
                    error = f"{type(exc).__name__}: {admission.get('reason', 'post-unload admission rejected')}"[:300]
                elif bool(getattr(exc, "preparation_cancelled", False)):
                    cancelled = True
                else:
                    error = f"{type(exc).__name__}: {exc}"[:300]
        if not cancelled and not error:
            observed_vram_bytes = self._observe_model_vram_bytes(
                target,
                should_stop=should_stop,
                deadline=deadline,
            )
        elapsed_ms = (time.perf_counter() - started) * 1000
        with self._cond:
            if observed_vram_bytes is not None:
                self._model_vram_bytes[target.strip().casefold()] = observed_vram_bytes
            self._stats["switch_time_ms"] = round(float(self._stats.get("switch_time_ms", 0.0)) + elapsed_ms, 1)
            self._stats["evictions"] += len(evicted)
            self._switch_sequence = max(0, int(getattr(self, "_switch_sequence", 0))) + 1
            switch_receipt = {
                "switch_event_id": self._switch_sequence,
                "model": target,
                "model_prepare_ms": round(prepare_duration_ms, 1),
                "model_switch_ms": round(elapsed_ms, 1),
                "evicted_models": list(evicted),
                "eviction_count": len(evicted),
                "vram_before_bytes": vram_before_bytes,
                "vram_after_bytes": observed_vram_bytes,
                "post_unload_admission": dict(post_unload_admission) if post_unload_admission is not None else None,
                "admission_rejected": admission_rejected,
                "success": not cancelled and not error and not admission_rejected,
                "cancelled": cancelled,
            }
            if error and not admission_rejected:
                switch_receipt["failure"] = True
            for job in self._pending:
                if job.model == target and not job.done.is_set():
                    job.model_switch_receipt = dict(switch_receipt)
                    if post_unload_admission is not None:
                        job.admission.update(post_unload_admission)
                        if post_unload_admission.get("state") == "admitted":
                            job.admission["state"] = "accepted"
            self._active_dispatched = 0
            self._last_switch = time.monotonic()
            if cancelled:
                now = time.monotonic()
                abandoned = [
                    job for job in self._pending
                    if job.model == target
                    and (
                        job.done.is_set()
                        or (job.cancel_event is not None and job.cancel_event.is_set())
                        or (job.deadline is not None and now >= job.deadline)
                    )
                ]
                for job in abandoned:
                    self._pending.remove(job)
                    self._stats["cancelled_pending"] += 1
                self._stats["model_switch_cancellations"] = int(self._stats.get("model_switch_cancellations", 0)) + 1
                # Preparation may already have unloaded the old model. Force the next
                # dispatch to re-check residency instead of trusting a stale affinity.
                self._active_model = None
                self._active_since = 0.0
            elif admission_rejected:
                self._stats["model_switch_admission_rejections"] = int(
                    self._stats.get("model_switch_admission_rejections", 0)
                ) + 1
                failed = [job for job in self._pending if job.model == target]
                for job in failed:
                    self._pending.remove(job)
                    reason = str((post_unload_admission or {}).get("reason", "post-unload admission rejected"))
                    job.error = f"model preparation admission rejected: {reason}"
                    job.finished_at = time.monotonic()
                    job.done.set()
                self._active_model = None
                self._active_since = 0.0
            elif error:
                self._stats["model_switch_failures"] += 1
                self._model_blocked_until[target] = time.monotonic() + self.switch_failure_cooldown
                self._model_last_error[target] = error
                # The switch happened with no in-flight work. Fail the already queued
                # requests for this model now; leaving them parked until a cooldown
                # expires turns a preparation failure into an apparent hub hang.
                failed = [job for job in self._pending if job.model == target]
                for job in failed:
                    self._pending.remove(job)
                    job.error = f"model preparation failed: {error}"
                    job.finished_at = time.monotonic()
                    job.done.set()
                self._active_model = None
                self._active_since = 0.0
            else:
                if target != self._active_model:
                    self._stats["model_switches"] += 1
                self._model_blocked_until.pop(target, None)
                self._model_last_error.pop(target, None)
                self._active_model = target
                self._active_since = time.monotonic()
            self._switching = False
            self._cond.notify_all()
        return not error and not cancelled and not admission_rejected

    def prewarm(self, model: str) -> bool:
        """Warm one model only while completely idle; never delays queued user work."""
        with self._cond:
            if self._pending or self._inflight or self._switching or self._background_gpu_lease:
                return False
            if self._active_model == model:
                return True
            self._switching = True
        success = self._perform_switch(model)
        if success:
            with self._cond:
                self._stats["prewarms"] += 1
        return success

    def _run_job(self, job: Job) -> None:
        job.started_at = time.monotonic()
        try:
            job.result = job.context.run(job.execute)
            if not isinstance(job.result, dict):
                job.result = {"success": True, "result": job.result}
            with self._cond:
                self._stats["completed"] += 1
                if job.background:
                    self._stats["background_completed"] += 1
                else:
                    self._last_foreground_activity = time.monotonic()
        except Exception as exc:
            job.error = str(exc)
            with self._cond:
                self._stats["failed"] += 1
                if job.background:
                    self._stats["background_failed"] += 1
                else:
                    self._last_foreground_activity = time.monotonic()
        finally:
            job.finished_at = time.monotonic()
            with self._cond:
                self._inflight -= 1
                self._inflight_jobs.pop(job.id, None)
                if job.background:
                    self._inflight_background = max(0, self._inflight_background - 1)
                current = self._inflight_by_tenant.get(job.tenant, 1) - 1
                if current <= 0:
                    self._inflight_by_tenant.pop(job.tenant, None)
                else:
                    self._inflight_by_tenant[job.tenant] = current
                job.done.set()
                self._cond.notify_all()

    def ensure_dispatcher(self) -> bool:
        with self._cond:
            if not self._running:
                return False
            if self._dispatcher.is_alive():
                return True
            self._dispatcher = threading.Thread(target=self._dispatch_loop, name="local-ai-dispatcher", daemon=True)
            self._dispatcher.start()
            self._cond.notify_all()
            return True

    def _job_public(self, job: Job, now: float, *, state: str, position: int = 0) -> dict[str, Any]:
        wait_ms = max(0, int(((job.started_at or now) - job.created_at) * 1000))
        service_ms = max(0, int((now - job.started_at) * 1000)) if job.started_at and state == "running" else 0
        if job.background:
            wait_reason = "background-idle"
        elif self._switching and job.model != self._active_model:
            wait_reason = "model-switch"
        elif job.model != self._active_model:
            wait_reason = "model-affinity"
        elif self._inflight_by_tenant.get(job.tenant, 0) >= self.max_inflight_per_tenant:
            wait_reason = "tenant-limit"
        elif self._inflight >= self._active_parallel_limit():
            wait_reason = "model-capacity"
        else:
            wait_reason = "ready"
        return {
            "job_id": job.id, "trace_id": job.trace_id, "state": state, "position": position,
            "model": job.model, "source": job.source, "tenant": job.tenant[:120],
            "priority": job.priority, "background": job.background,
            "created_at": job.created_wall, "wait_ms": wait_ms, "service_ms": service_ms,
            "wait_reason": wait_reason, "caller_timed_out": job.caller_timed_out,
            "admission": {**job.admission, "queue_age_ms": wait_ms},
            "admission_state": job.admission.get("state", "accepted"),
        }

    def status(self) -> dict[str, Any]:
        with self._cond:
            by_model: dict[str, int] = {}
            by_tenant: dict[str, int] = {}
            background_queued = 0
            now = time.monotonic()
            ordered_pending = sorted(self._pending, key=lambda j: (-j.priority, j.created_at))
            pending_jobs: list[dict[str, Any]] = []
            model_positions: dict[str, int] = {}
            for job in ordered_pending:
                by_model[job.model] = by_model.get(job.model, 0) + 1
                by_tenant[job.tenant] = by_tenant.get(job.tenant, 0) + 1
                background_queued += int(job.background)
                model_positions[job.model] = model_positions.get(job.model, 0) + 1
                if len(pending_jobs) < self.status_max_items:
                    item = self._job_public(job, now, state="queued", position=model_positions[job.model])
                    pending_jobs.append(item)
            inflight_jobs = [self._job_public(job, now, state="running") for job in sorted(self._inflight_jobs.values(), key=lambda j: j.started_at or j.created_at)]
            return {
                "active_model": self._active_model,
                "active_parallel_limit": self._active_parallel_limit(),
                "global_parallel_limit": self.max_parallel,
                "switching": self._switching,
                "background_gpu_lease": self._background_gpu_lease,
                "inflight": self._inflight,
                "inflight_background": self._inflight_background,
                "foreground_inflight": self._inflight - self._inflight_background,
                "queued": len(self._pending),
                "background_queued": background_queued,
                "foreground_queued": len(self._pending) - background_queued,
                "queued_by_model": by_model,
                "queued_by_tenant": by_tenant,
                "pending_jobs": pending_jobs,
                "pending_jobs_total": len(self._pending),
                "pending_jobs_truncated": len(self._pending) > self.status_max_items,
                "inflight_jobs": inflight_jobs,
                "active_batch_dispatched": self._active_dispatched,
                "background_allowed": self.background_allowed(),
                "blocked_models": {m: max(0, int((until - now) * 1000)) for m, until in self._model_blocked_until.items() if until > now},
                "last_foreground_activity_ms": max(0, int((now - self._last_foreground_activity) * 1000)),
                "stats": dict(self._stats),
                "cache_stats": self._cache_stats(),
            }

    def close(self) -> None:
        with self._cond:
            self._running = False
            # Release callers waiting on jobs that will never be dispatched.
            for job in self._pending:
                job.error = "scheduler shutting down"
                job.done.set()
            self._pending.clear()
            # Running work can only stop cooperatively. Signal each caller-owned
            # cancellation event before shutting down the executor.
            for job in self._inflight_jobs.values():
                if job.cancel_event is not None:
                    job.cancel_event.set()
            self._cond.notify_all()
        self._executor.shutdown(wait=False, cancel_futures=True)
        if self._dispatcher.is_alive() and threading.current_thread() is not self._dispatcher:
            self._dispatcher.join(timeout=1.0)
