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
        self._last_status: dict[str, Any] = {}
        self._last_check_time = 0.0
        self._pinned_model: str | None = None
        self._pin_expires: float = 0.0

    def status(self, force: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            if not force and self._last_status and (now - self._last_check_time < 2.0):
                return dict(self._last_status)

            gpu = get_gpu_telemetry()
            available = bool(gpu.get("available", False))
            total_mb = float(gpu.get("vram_total_mb", 0) or gpu.get("unified_memory_mb", 0) or 0)
            used_mb = float(gpu.get("vram_used_mb", 0) or 0)
            avail_mb = max(0.0, total_mb - used_mb) if total_mb > 0 else 0.0
            used_pct = float(gpu.get("vram_used_pct", 0) or (round(100.0 * used_mb / max(1.0, total_mb), 1) if total_mb > 0 else 0.0))

            if not available or total_mb <= 0:
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
            target_model = str(models_cfg.get("fast_code", "qwen2.5-coder:7b"))
            draft_model = str(models_cfg.get("draft_code", "qwen2.5-coder:1.5b"))

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
            return res

    def pin_model(self, model_name: str, ttl_seconds: float = 300.0) -> dict[str, Any]:
        """Pin a warm model in VRAM to prevent cache thrashing."""
        with self._lock:
            self._pinned_model = str(model_name).strip()
            self._pin_expires = time.monotonic() + max(0.001, float(ttl_seconds))
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
            self._pinned_model = None
            return None

    def unpin_model(self) -> None:
        """Clear warm model pin."""
        with self._lock:
            self._pinned_model = None
            self._pin_expires = 0.0

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
            "target_model": spec.get("target_model", "qwen2.5-coder:7b"),
            "draft_model": spec.get("draft_model", "qwen2.5-coder:1.5b"),
            "strategy": spec.get("strategy", "full_capacity"),
        }
