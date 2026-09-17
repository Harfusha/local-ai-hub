from __future__ import annotations

from .json_utils import dumps as json_dumps

from . import __version__
import json
import math
import threading
import time
from pathlib import Path
from typing import Any


class RuntimeTuner:
    """Low-overhead EMA latency/load profile for residency decisions.

    It never changes semantic model roles by itself. It only helps decide between
    explicitly quality-equivalent resident candidates, preserving requested quality gates.
    """

    def __init__(self, config: dict[str, Any]):
        cfg = config.get("autotune", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.alpha = min(1.0, max(0.01, float(cfg.get("ema_alpha", 0.20))))
        self.min_samples = max(1, int(cfg.get("min_samples", 2)))
        self.resident_latency_ratio = max(0.5, float(cfg.get("resident_latency_ratio", 1.15)))
        self._lock = threading.RLock()
        self._models: dict[str, dict[str, float]] = {}
        self._persist_enabled = bool(cfg.get("persist", True))
        self._persist_interval_seconds = max(0.0, float(cfg.get("persist_interval_seconds", 15.0)))
        state_dir = Path(str(config.get("server", {}).get("state_dir", "~/.local-ai-hub/state"))).expanduser()
        self._state_path = state_dir / "runtime-tuner.json"
        self._last_persist_seconds = 0.0
        self._load_state()

    @staticmethod
    def _profile(data: Any) -> dict[str, float] | None:
        if not isinstance(data, dict):
            return None
        try:
            profile = {
                key: float(data[key])
                for key in ("latency_ms", "load_ms", "tps", "samples")
            }
        except (KeyError, TypeError, ValueError):
            return None
        if any(not math.isfinite(value) or value < 0 for value in profile.values()):
            return None
        return profile

    def _load_state(self) -> None:
        if not self.enabled or not self._persist_enabled:
            return
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or str(raw.get("version", "")) != __version__:
                return
            rows = raw.get("models", {})
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(rows, dict):
            return
        restored: dict[str, dict[str, float]] = {}
        for model, data in rows.items():
            name = str(model)
            profile = self._profile(data)
            if profile is not None and name and len(name) <= 256:
                restored[name] = profile
        with self._lock:
            self._models = restored

    def _persist_locked(self, *, force: bool = False) -> None:
        if not self.enabled or not self._persist_enabled:
            return
        now = time.monotonic()
        if not force and now - self._last_persist_seconds < self._persist_interval_seconds:
            return
        payload = {"version": __version__, "models": self._models}
        temporary = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json_dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
            temporary.replace(self._state_path)
            self._last_persist_seconds = now
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def observe(self, model: str, result: dict[str, Any], elapsed_ms: float) -> None:
        if not self.enabled or not model:
            return
        load_ms = float(result.get("load_duration_ns", 0) or 0) / 1e6
        tokens = float(result.get("eval_count", 0) or 0)
        eval_seconds = float(result.get("eval_duration_ns", 0) or 0) / 1e9
        tps = tokens / max(0.001, eval_seconds) if tokens else 0.0
        with self._lock:
            current = self._models.setdefault(
                model,
                {"latency_ms": float(elapsed_ms), "load_ms": load_ms, "tps": tps, "samples": 0.0},
            )
            samples_before = float(current.get("samples", 0.0))
            alpha = self.alpha
            for key, value in (("latency_ms", float(elapsed_ms)), ("load_ms", load_ms), ("tps", tps)):
                current[key] = (1 - alpha) * float(current[key]) + alpha * value
            current["samples"] = float(current.get("samples", 0.0)) + 1.0
            self._persist_locked(force=samples_before < self.min_samples <= current["samples"])

    def estimated_ms(self, model: str, active: str | None = None) -> float:
        with self._lock:
            data = dict(self._models.get(model, {}))
        base = float(data.get("latency_ms", 10_000.0))
        if active and active != model:
            base += float(data.get("load_ms", 0.0))
        return base

    def ready(self, *models: str) -> bool:
        if not self.enabled or not models:
            return False
        with self._lock:
            return all(float(self._models.get(model, {}).get("samples", 0)) >= self.min_samples for model in models if model)

    def prefer_resident(self, desired: str, resident: str) -> bool:
        """Return True only when enough observations suggest residency is faster."""
        if not self.enabled or not desired or not resident or desired == resident:
            return desired == resident
        with self._lock:
            desired_data = dict(self._models.get(desired, {}))
            resident_data = dict(self._models.get(resident, {}))
        if min(float(desired_data.get("samples", 0)), float(resident_data.get("samples", 0))) < self.min_samples:
            return False
        desired_cost = self.estimated_ms(desired, active=resident)
        resident_cost = self.estimated_ms(resident, active=resident)
        return resident_cost <= desired_cost * self.resident_latency_ratio

    def stats(self) -> dict[str, Any]:
        with self._lock:
            models = {
                model: {key: (round(value, 2) if isinstance(value, (int, float)) else value) for key, value in data.items()}
                for model, data in self._models.items()
            }
        return {
            "enabled": self.enabled,
            "min_samples": self.min_samples,
            "resident_latency_ratio": self.resident_latency_ratio,
            "persistence_enabled": self._persist_enabled,
            "models": models,
        }
