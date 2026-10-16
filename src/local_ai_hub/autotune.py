from __future__ import annotations

from .json_utils import dumps as json_dumps

from . import __version__
import json
import math
import threading
import time
from collections.abc import Mapping
from numbers import Real
from pathlib import Path
from typing import Any

from .state_paths import configured_state_dir


def _finite_config_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"autotune.{field} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        raise ValueError(f"autotune.{field} must be a finite number") from None
    if not math.isfinite(number):
        raise ValueError(f"autotune.{field} must be a finite number")
    return number


def _finite_nonnegative_metric(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


class RuntimeTuner:
    """Low-overhead EMA latency/load profile for residency decisions.

    It never changes semantic model roles by itself. It only helps decide between
    explicitly quality-equivalent resident candidates, preserving requested quality gates.
    """

    def __init__(self, config: Mapping[str, Any] | None = None):
        if config is None:
            config = {}
        if not isinstance(config, Mapping):
            raise TypeError("config must be a mapping or None")
        cfg = config.get("autotune", {})
        if not isinstance(cfg, Mapping):
            raise TypeError("config.autotune must be a mapping")
        self.enabled = bool(cfg.get("enabled", True))
        alpha = _finite_config_number(cfg.get("ema_alpha", 0.20), "ema_alpha")
        resident_ratio = _finite_config_number(
            cfg.get("resident_latency_ratio", 1.15), "resident_latency_ratio"
        )
        persist_interval = _finite_config_number(
            cfg.get("persist_interval_seconds", 15.0), "persist_interval_seconds"
        )
        min_samples = cfg.get("min_samples", 2)
        if (
            isinstance(min_samples, bool)
            or not isinstance(min_samples, int)
            or min_samples < 1
        ):
            raise ValueError("autotune.min_samples must be a positive integer")
        self.alpha = min(1.0, max(0.01, alpha))
        self.min_samples = min_samples
        self.resident_latency_ratio = max(0.5, resident_ratio)
        self._lock = threading.RLock()
        self._models: dict[str, dict[str, float]] = {}
        self._persist_enabled = bool(cfg.get("persist", True))
        self._persist_interval_seconds = max(0.0, persist_interval)
        state_dir = configured_state_dir(config, create=False)
        self._state_path = state_dir / "runtime-tuner.json"
        self._last_persist_seconds = 0.0
        self._load_state()

    @staticmethod
    def _profile(data: Any) -> dict[str, float] | None:
        if not isinstance(data, dict):
            return None
        profile: dict[str, float] = {}
        for key in ("latency_ms", "load_ms", "tps", "samples"):
            raw_value = data.get(key)
            if key not in data or isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                return None
            try:
                value = float(raw_value)
            except (OverflowError, TypeError, ValueError):
                return None
            if not math.isfinite(value) or value < 0:
                return None
            profile[key] = value
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

    def observe(self, model: str, result: Mapping[str, Any], elapsed_ms: float) -> None:
        if not self.enabled:
            return
        if not isinstance(model, str) or not model.strip() or not isinstance(result, Mapping):
            return
        latency_ms = _finite_nonnegative_metric(elapsed_ms)
        if latency_ms is None:
            return
        metrics = {}
        for key in ("load_duration_ns", "eval_count", "eval_duration_ns"):
            value = _finite_nonnegative_metric(result[key]) if key in result else 0.0
            if value is None:
                return
            metrics[key] = value
        load_ms = metrics["load_duration_ns"] / 1e6
        tokens = metrics["eval_count"]
        eval_seconds = metrics["eval_duration_ns"] / 1e9
        if tokens == 0 or eval_seconds == 0:
            tps = 0.0
        else:
            try:
                tps = tokens / max(0.001, eval_seconds)
            except (OverflowError, ZeroDivisionError):
                return
            if not math.isfinite(tps):
                return
        with self._lock:
            current = self._models.setdefault(
                model,
                {"latency_ms": latency_ms, "load_ms": load_ms, "tps": tps, "samples": 0.0},
            )
            samples_before = float(current.get("samples", 0.0))
            alpha = self.alpha
            for key, value in (("latency_ms", latency_ms), ("load_ms", load_ms), ("tps", tps)):
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

    def has_model(self, model: str) -> bool:
        if not model or not isinstance(model, str):
            return False
        with self._lock:
            return model in self._models

    def get_model_profile(self, model: str) -> dict[str, float] | None:
        with self._lock:
            profile = self._models.get(model)
            return dict(profile) if profile is not None else None

    def model_names(self) -> list[str]:
        with self._lock:
            return list(self._models.keys())

    def reset(self, model: str | None = None) -> None:
        with self._lock:
            if model is None:
                self._models.clear()
            else:
                self._models.pop(model, None)
            self._persist_locked(force=True)

