from __future__ import annotations

import threading
import time
from typing import Any

from .gpu_monitor import get_gpu_telemetry


class VRAMBalancer:
    """Hardware-adaptive GPU VRAM pressure monitor and speculative inference balancer.

    Monitors dedicated/unified GPU graphics memory, dynamically scales context token budgets,
    pairs fast draft models for speculative decoding, and signals background worker throttling
    to prevent desktop GPU OOM crashes.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
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
        with self._condition:
            request_generation = self._status_generation
            now = time.monotonic()
            if not force and self._last_status and (now - self._last_check_time < 2.0):
                return dict(self._last_status)

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
                self._sampling = True
                threading.Thread(target=self._sample_gpu_telemetry, daemon=True).start()

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
        """Return conservative status when a telemetry probe stalls.

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

    def _status_from_telemetry(self, gpu: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            available = bool(gpu.get("available", False))
            is_integrated = bool(gpu.get("integrated", False)) or bool(gpu.get("shared_memory", False))
            total_mb = float(gpu.get("vram_total_mb", 0) or gpu.get("unified_memory_mb", 0) or 0)
            used_mb = float(gpu.get("vram_used_mb", 0) or 0)
            avail_mb = max(0.0, total_mb - used_mb) if total_mb > 0 else 0.0
            used_pct = float(gpu.get("vram_used_pct", 0) or (round(100.0 * used_mb / max(1.0, total_mb), 1) if total_mb > 0 else 0.0))

            if not available or total_mb <= 0 or is_integrated:
                level = "nominal"
                factor = 1.0
                strategy = "full_capacity"
                throttle = False
            elif used_pct >= 95.0 or avail_mb < 1024:
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
                "vram_used_mb": used_mb,
                "vram_available_mb": avail_mb,
                "vram_used_pct": used_pct,
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
        with self._lock:
            self._pinned_model = str(model_name).strip()
            self._pin_expires = time.monotonic() + max(0.001, float(ttl_seconds))
            self._invalidate_status_locked()
            return {
                "pinned": True,
                "model": self._pinned_model,
                "ttl_seconds": float(ttl_seconds),
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
        st = self.status()
        factor = float(st.get("context_budget_factor", 1.0))
        return max(4096, int(base_tokens * factor))

    def get_speculative_pairing(self) -> dict[str, str]:
        """Return target and draft models for speculative decoding."""
        st = self.status()
        spec = st.get("speculative_inference", {})
        return {
            "target_model": spec.get("target_model", "qwen2.5-coder:3b"),
            "draft_model": spec.get("draft_model", "qwen2.5-coder:7b"),
            "strategy": spec.get("strategy", "full_capacity"),
        }
