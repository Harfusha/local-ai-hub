from __future__ import annotations

import threading
import time
import math
import numbers
from typing import Any

from .gpu_monitor import get_gpu_telemetry


class VRAMBalancer:
    """Hardware-adaptive GPU VRAM pressure monitor and speculative inference balancer.

    Monitors dedicated/unified GPU graphics memory, dynamically scales context token budgets,
    pairs fast draft models for speculative decoding, and signals background worker throttling
    to prevent desktop GPU OOM crashes.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = dict(config) if isinstance(config, dict) else {}
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._sampling = False
        self._sample_wait_timeout_seconds = 3.0
        self._last_status: dict[str, Any] = {}
        self._last_check_time = 0.0
        self._status_generation = 0
        self._pinned_model: str | None = None
        self._pin_expires: float = 0.0

    def status(self, force: bool = False) -> dict[str, Any]:
        """Read cached pressure without waiting; force explicitly requests a bounded refresh."""
        with self._condition:
            request_generation = self._status_generation
            now = time.monotonic()
            if not force and self._last_status and (now - self._last_check_time < 2.0):
                return dict(self._last_status)

            if not force:
                if not self._sampling:
                    self._start_sampling_locked()
                result = self._sampling_timeout_fallback_locked()
                result["telemetry_wait_timed_out"] = False
                result["telemetry_error"] = "sample_pending" if self._sampling else "sample_start_failed"
                result["telemetry_sampling"] = self._sampling
                return result

            wait_deadline = time.monotonic() + self._sample_wait_timeout_seconds
            while self._sampling:
                remaining = wait_deadline - time.monotonic()
                if remaining <= 0:
                    return self._sampling_timeout_fallback_locked()
                self._condition.wait(timeout=remaining)
                if self._status_generation > request_generation and self._last_status:
                    return dict(self._last_status)
                now = time.monotonic()
                if not force and self._last_status and (now - self._last_check_time < 2.0):
                    return dict(self._last_status)

            if not self._sampling:
                if time.monotonic() >= wait_deadline:
                    return self._sampling_timeout_fallback_locked()
                self._start_sampling_locked()
                if not self._sampling:
                    result = self._sampling_timeout_fallback_locked()
                    result["telemetry_wait_timed_out"] = False
                    result["telemetry_error"] = "sample_start_failed"
                    return result

            while self._sampling:
                remaining = wait_deadline - time.monotonic()
                if remaining <= 0:
                    return self._sampling_timeout_fallback_locked()
                self._condition.wait(timeout=remaining)
                if self._status_generation > request_generation and self._last_status:
                    return dict(self._last_status)
            if self._status_generation > request_generation and self._last_status:
                return dict(self._last_status)
            if not force and self._last_status and (time.monotonic() - self._last_check_time < 2.0):
                return dict(self._last_status)
            return self._sampling_timeout_fallback_locked()

    def _start_sampling_locked(self) -> None:
        """Start at most one bounded probe; caller holds the state condition."""
        self._sampling = True
        try:
            threading.Thread(target=self._sample_gpu_telemetry, daemon=True, name="vram-telemetry").start()
        except RuntimeError:
            self._sampling = False
            self._condition.notify_all()

    def _sample_gpu_telemetry(self) -> None:
        try:
            # GPU telemetry can invoke bounded subprocess probes. Keep those waits
            # out of the state lock and status caller so both stay responsive.
            self._status_from_telemetry(get_gpu_telemetry())
        except Exception:
            with self._condition:
                fallback = self._sampling_timeout_fallback_locked()
                fallback["telemetry_error"] = "sample_failed"
                self._last_status = fallback
                self._last_check_time = time.monotonic()
                self._status_generation += 1
        finally:
            with self._condition:
                self._sampling = False
                self._condition.notify_all()

    def _sampling_timeout_fallback_locked(self) -> dict[str, Any]:
        """Return conservative status when another telemetry probe stalls.

        Caller holds ``_condition``. Never start a duplicate probe after timeout.
        """
        now = time.monotonic()
        if self._last_status:
            result = dict(self._last_status)
            result["available"] = False
            result["pressure_level"] = "unknown"
            result["context_budget_factor"] = min(
                0.25, float(result.get("context_budget_factor", 0.25) or 0.25)
            )
            result["dynamic_context_tokens"] = max(
                0, int((result.get("dynamic_context_tokens", 0) or 0) * 0.25)
            )
            speculative = result.get("speculative_inference")
            if isinstance(speculative, dict):
                result["speculative_inference"] = dict(speculative)
                result["speculative_inference"]["active"] = False
                result["speculative_inference"]["strategy"] = "telemetry_unavailable"
        else:
            models_cfg = self.config.get("models", {})
            result = {
                "available": False,
                "gpu_name": "GPU",
                "vendor": "unknown",
                "vram_total_mb": 0.0,
                "vram_used_mb": 0.0,
                "vram_available_mb": 0.0,
                "vram_used_pct": 0.0,
                "pressure_level": "unknown",
                "context_budget_factor": 0.25,
                "dynamic_context_tokens": 0,
                "throttle_background": True,
                "speculative_inference": {
                    "draft_model": str(models_cfg.get("draft_code", "qwen2.5-coder:3b")),
                    "target_model": str(models_cfg.get("fast_code", "qwen2.5-coder:1.5b")),
                    "strategy": "telemetry_unavailable",
                    "active": False,
                },
                "pinned_model": None,
            }
        result["available"] = False
        result["pressure_level"] = "unknown"
        result["context_budget_factor"] = min(
            0.25, float(result.get("context_budget_factor", 0.25) or 0.25)
        )
        result["throttle_background"] = True
        result["telemetry_stale"] = True
        result["telemetry_wait_timed_out"] = True
        result["telemetry_error"] = "sample_wait_timeout"
        if self._pinned_model and self._pin_expires > now:
            result["pinned_model"] = {
                "model": self._pinned_model,
                "ttl_remaining_seconds": round(max(0.0, self._pin_expires - now), 1),
            }
        else:
            result["pinned_model"] = None
        return result

    @staticmethod
    def _safe_float(val: Any, default: float = 0.0) -> float:
        if isinstance(val, bool):
            return default
        try:
            res = float(val or 0)
            return res if math.isfinite(res) else default
        except (TypeError, ValueError, OverflowError):
            return default

    def _status_from_telemetry(self, gpu: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            def unknown_sample(reason: str) -> dict[str, Any]:
                result = self._sampling_timeout_fallback_locked()
                result["telemetry_wait_timed_out"] = False
                result["telemetry_error"] = reason
                self._last_status = result
                self._last_check_time = now
                self._status_generation += 1
                return result

            if not isinstance(gpu, dict):
                return unknown_sample("sample_invalid")
            if gpu.get("available") is False:
                return unknown_sample("sample_unavailable")
            if gpu.get("available") is not True:
                return unknown_sample("sample_invalid")
            available = True

            for key in ("integrated", "shared_memory"):
                if key in gpu and not isinstance(gpu[key], bool):
                    return unknown_sample("sample_invalid")
            is_integrated = gpu.get("integrated", False) or gpu.get("shared_memory", False)

            metric_names = (
                "vram_total_mb",
                "unified_memory_mb",
                "reported_adapter_memory_mb",
                "vram_used_mb",
                "unified_memory_used_mb",
                "shared_memory_used_mb",
                "vram_available_mb",
                "unified_memory_available_mb",
                "shared_memory_available_mb",
                "vram_used_pct",
                "unified_memory_used_pct",
                "shared_memory_used_pct",
            )
            metrics: dict[str, float | None] = {}
            for key in metric_names:
                if key not in gpu or gpu[key] is None:
                    metrics[key] = None
                    continue
                raw_value = gpu[key]
                if isinstance(raw_value, bool) or not isinstance(raw_value, numbers.Real):
                    return unknown_sample("sample_invalid")
                try:
                    value = float(raw_value)
                except (OverflowError, TypeError, ValueError):
                    return unknown_sample("sample_invalid")
                if not math.isfinite(value) or value < 0:
                    return unknown_sample("sample_invalid")
                if key.endswith("_pct") and value > 100:
                    return unknown_sample("sample_invalid")
                metrics[key] = value

            dedicated_keys = (
                "vram_used_mb",
                "vram_available_mb",
                "vram_used_pct",
            )
            shared_keys = (
                "unified_memory_used_mb",
                "shared_memory_used_mb",
                "unified_memory_available_mb",
                "shared_memory_available_mb",
                "unified_memory_used_pct",
                "shared_memory_used_pct",
            )

            def has_measured_pool(keys: tuple[str, ...]) -> bool:
                return any(metrics[key] is not None for key in keys)

            # Never compare usage from one memory pool with another pool's capacity.
            # Windows' reported adapter size and zeroed VRAM fields are inventory only.
            if "reported_adapter_memory_mb" in gpu and not is_integrated:
                pool_keys: tuple[str, ...] = ()
                total_mb = 0.0
                measurement_basis = "inventory_only"
            elif is_integrated:
                if (
                    metrics["unified_memory_mb"] is not None
                    and metrics["unified_memory_mb"] > 0
                    and has_measured_pool(shared_keys)
                ):
                    pool_keys = shared_keys
                    total_mb = metrics["unified_memory_mb"]
                    measurement_basis = "shared_unified_observed"
                elif (
                    metrics["vram_total_mb"] is not None
                    and metrics["vram_total_mb"] > 0
                    and has_measured_pool(dedicated_keys)
                ):
                    pool_keys = dedicated_keys
                    total_mb = metrics["vram_total_mb"]
                    measurement_basis = "dedicated_observed"
                else:
                    pool_keys = ()
                    total_mb = 0.0
                    measurement_basis = "unmeasured"
            elif (
                metrics["vram_total_mb"] is not None
                and metrics["vram_total_mb"] > 0
                and has_measured_pool(dedicated_keys)
            ):
                pool_keys = dedicated_keys
                total_mb = metrics["vram_total_mb"]
                measurement_basis = "dedicated_observed"
            elif (
                metrics["unified_memory_mb"] is not None
                and metrics["unified_memory_mb"] > 0
                and has_measured_pool(shared_keys)
            ):
                pool_keys = shared_keys
                total_mb = metrics["unified_memory_mb"]
                measurement_basis = "shared_unified_observed"
            else:
                pool_keys = ()
                total_mb = 0.0
                measurement_basis = "unmeasured"

            if total_mb <= 0 or not pool_keys:
                return unknown_sample("sample_unavailable")

            measured_percentages = [
                metrics[key]
                for key in pool_keys
                if key.endswith("_pct") and metrics[key] is not None
            ]
            measured_used = [
                metrics[key]
                for key in pool_keys
                if key.endswith("_used_mb") and metrics[key] is not None
            ]
            measured_available = [
                metrics[key]
                for key in pool_keys
                if key.endswith("_available_mb") and metrics[key] is not None
            ]
            pressure_percentages = list(measured_percentages)
            for used_value in measured_used:
                if used_value > total_mb:
                    return unknown_sample("sample_invalid")
                pressure_percentages.append(100.0 * used_value / total_mb)
            for available_value in measured_available:
                if available_value > total_mb:
                    return unknown_sample("sample_invalid")
                pressure_percentages.append(100.0 * (total_mb - available_value) / total_mb)

            policy_pressure_pct = round(max(pressure_percentages), 4)
            policy_headroom_mb = round(
                min(total_mb * (1.0 - value / 100.0) for value in pressure_percentages),
                4,
            )
            # Preserve telemetry as reported. Policy bounds above may combine
            # contradictory measurements conservatively, but are never raw readings.
            used_pct = policy_pressure_pct
            avail_mb = policy_headroom_mb

            if used_pct >= 95.0 or avail_mb < 1024:
                level = "critical"
                factor = 0.25
                strategy = "fast_tier_throttled"
                throttle = True
            elif used_pct >= 85.0 or avail_mb < 2048:
                level = "high"
                factor = 0.5
                strategy = "speculative_draft_or_fast_tier"
                throttle = True
            elif used_pct >= 70.0 or avail_mb < 4096:
                level = "moderate"
                factor = 0.75
                strategy = "speculative_draft_recommended"
                throttle = False
            else:
                level = "nominal"
                factor = 1.0
                strategy = "full_capacity"
                throttle = False

            base_context = int(self.config.get("token_budget", {}).get("default_context", 32768))
            dynamic_context = max(4096, int(base_context * factor))

            models_cfg = self.config.get("models", {})
            target_model = str(models_cfg.get("fast_code", "qwen2.5-coder:1.5b"))
            draft_model = str(models_cfg.get("draft_code", "qwen2.5-coder:3b"))

            res = {
                "available": available,
                "gpu_name": gpu.get("gpu_name", "GPU"),
                "vendor": gpu.get("vendor", "unknown"),
                "vram_total_mb": total_mb,
                "vram_used_mb": metrics["vram_used_mb"],
                "vram_available_mb": metrics["vram_available_mb"],
                "vram_used_pct": metrics["vram_used_pct"],
                "policy_pressure_pct": policy_pressure_pct,
                "policy_headroom_mb": policy_headroom_mb,
                "policy_measurement_basis": measurement_basis,
                "policy_pressure_is_derived": (
                    not bool(measured_percentages)
                    or policy_pressure_pct > max(measured_percentages)
                ),
                "pressure_level": level,
                "context_budget_factor": factor,
                "dynamic_context_tokens": dynamic_context,
                "throttle_background": throttle,
                "speculative_inference": {
                    "draft_model": draft_model,
                    "target_model": target_model,
                    "strategy": strategy,
                    "active": level in {"moderate", "high"},
                },
                "pinned_model": (
                    {
                        "model": self._pinned_model,
                        "ttl_remaining_seconds": round(max(0.0, self._pin_expires - now), 1),
                    }
                    if (self._pinned_model and now < self._pin_expires)
                    else None
                ),
            }
            if self._pinned_model and now >= self._pin_expires:
                self._pinned_model = None
            self._last_status = res
            self._last_check_time = now
            self._status_generation += 1
            return res

    def sample_vram(self) -> dict[str, Any]:
        """Take a fresh VRAM snapshot for benchmark measurements."""
        return dict(self.status(force=True))

    def _invalidate_status_locked(self) -> None:
        """Invalidate cached pin metadata; caller must hold ``_lock``."""
        self._last_status = {}
        self._last_check_time = 0.0
        self._status_generation += 1

    def pin_model(self, model_name: str, ttl_seconds: float = 300.0) -> dict[str, Any]:
        """Pin a warm model in VRAM to prevent cache thrashing."""
        if not isinstance(model_name, str) or not model_name.strip() or "\x00" in model_name:
            raise ValueError("model_name must be a non-empty string")
        try:
            ttl = float(ttl_seconds)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("ttl_seconds must be finite and positive") from exc
        if isinstance(ttl_seconds, bool) or not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("ttl_seconds must be finite and positive")
        with self._lock:
            self._pinned_model = model_name.strip()
            self._pin_expires = time.monotonic() + ttl
            self._invalidate_status_locked()
            return {
                "pinned": True,
                "model": self._pinned_model,
                "ttl_seconds": ttl,
            }

    def get_pinned_model(self) -> str | None:
        """Return currently warm-pinned model if TTL has not expired."""
        with self._lock:
            if self._pinned_model and time.monotonic() < self._pin_expires:
                return self._pinned_model
            if self._pinned_model is not None:
                self._invalidate_status_locked()
            self._pinned_model = None
            return None

    def is_model_pinned(self, model_name: str) -> bool:
        """Return True if model is currently warm-pinned and not expired."""
        target = model_name.strip() if isinstance(model_name, str) and "\x00" not in model_name else ""
        if not target:
            return False
        pinned = self.get_pinned_model()
        return pinned == target

    def pinned_model_info(self) -> dict[str, Any] | None:
        """Return active pin metadata if model is currently pinned."""
        with self._lock:
            now = time.monotonic()
            if self._pinned_model and now < self._pin_expires:
                return {
                    "model": self._pinned_model,
                    "ttl_remaining_seconds": round(max(0.0, self._pin_expires - now), 1),
                }
            if self._pinned_model is not None:
                self._invalidate_status_locked()
                self._pinned_model = None
            return None

    def unpin_model(self) -> None:
        """Clear warm model pin."""
        with self._lock:
            self._pinned_model = None
            self._pin_expires = 0.0
            self._invalidate_status_locked()

    def should_throttle_background(self) -> bool:
        """Return True if VRAM pressure requires background GPU tasks to pause or downscale."""
        st = self.status()
        return bool(st.get("throttle_background", False))

    def recommended_context_budget(self, base_tokens: int = 32768) -> int:
        """Compute dynamically scaled context tokens based on graphics memory headroom."""
        if isinstance(base_tokens, bool) or not isinstance(base_tokens, int) or base_tokens < 1:
            raise ValueError("base_tokens must be a positive integer")
        st = self.status()
        try:
            factor = float(st.get("context_budget_factor", 1.0))
        except (TypeError, ValueError, OverflowError):
            factor = 0.125
        if not math.isfinite(factor):
            factor = 0.125
        factor = min(1.0, max(0.0, factor))
        numerator, denominator = factor.as_integer_ratio()
        return max(min(4096, base_tokens), base_tokens * numerator // denominator)

    def get_speculative_pairing(self) -> dict[str, str]:
        """Return target and draft models for speculative decoding."""
        st = self.status()
        spec = st.get("speculative_inference", {})
        return {
            "target_model": spec.get("target_model", "qwen2.5-coder:3b"),
            "draft_model": spec.get("draft_model", "qwen2.5-coder:7b"),
            "strategy": spec.get("strategy", "full_capacity"),
        }

    def is_sampling(self) -> bool:
        """Return True if GPU telemetry sampling thread is currently active."""
        with self._lock:
            return bool(self._sampling)

    def active_pinned_model(self) -> str | None:
        """Return name of currently pinned model if any."""
        return self.get_pinned_model()

    def current_pressure_level(self) -> str:
        """Return current pressure level string."""
        st = self.status()
        return str(st.get("pressure_level", "unknown"))
