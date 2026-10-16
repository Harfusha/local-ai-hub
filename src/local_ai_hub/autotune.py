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

    def __init__(self, config: dict[str, Any] | None = None):
        clean_cfg = config if isinstance(config, dict) else {}
        cfg = clean_cfg.get("autotune") if isinstance(clean_cfg.get("autotune"), dict) else {}
        self.enabled = bool(cfg.get("enabled", True))
        try:
            raw_alpha = float(cfg.get("ema_alpha", 0.20))
            if not math.isfinite(raw_alpha):
                raw_alpha = 0.20
        except (TypeError, ValueError):
            raw_alpha = 0.20
        self.alpha = min(1.0, max(0.01, raw_alpha))

        try:
            raw_min = int(cfg.get("min_samples", 2))
        except (TypeError, ValueError):
            raw_min = 2
        self.min_samples = max(1, raw_min)

        try:
            raw_ratio = float(cfg.get("resident_latency_ratio", 1.15))
            if not math.isfinite(raw_ratio):
                raw_ratio = 1.15
        except (TypeError, ValueError):
            raw_ratio = 1.15
        self.resident_latency_ratio = max(0.5, raw_ratio)

        self._lock = threading.RLock()
        self._models: dict[str, dict[str, float]] = {}
        self._persist_enabled = bool(cfg.get("persist", True))
        try:
            raw_interval = float(cfg.get("persist_interval_seconds", 15.0))
            if not math.isfinite(raw_interval):
                raw_interval = 15.0
        except (TypeError, ValueError):
            raw_interval = 15.0
        self._persist_interval_seconds = max(0.0, raw_interval)

        server_cfg = clean_cfg.get("server") if isinstance(clean_cfg.get("server"), dict) else {}
        raw_state_dir = server_cfg.get("state_dir") if isinstance(server_cfg, dict) else None
        if isinstance(raw_state_dir, str) and "\0" not in raw_state_dir:
            try:
                state_dir = Path(raw_state_dir).expanduser()
            except (ValueError, OSError):
                state_dir = Path("~/.local-ai-hub/state").expanduser()
        else:
            state_dir = Path("~/.local-ai-hub/state").expanduser()
        self._state_path = state_dir / "runtime-tuner.json"
        self._last_persist_seconds = 0.0
        self._load_state()

    @staticmethod
    def _profile(data: Any) -> dict[str, float] | None:
        if not isinstance(data, dict):
            return None
        try:
            profile: dict[str, float] = {}
            for key in ("latency_ms", "load_ms", "tps", "samples"):
                val = data[key]
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    return None
                fval = float(val)
                if not math.isfinite(fval) or fval < 0:
                    return None
                profile[key] = fval
        except (KeyError, TypeError, ValueError):
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
        if not self.enabled or not model or not isinstance(model, str) or not isinstance(result, dict):
            return
        try:
            val_elapsed = float(elapsed_ms)
            if not math.isfinite(val_elapsed) or val_elapsed < 0:
                return
        except (TypeError, ValueError):
            return

        def _safe_float(val: Any, default: float = 0.0) -> float:
            if isinstance(val, bool) or val is None:
                return default
            try:
                res = float(val)
                return res if math.isfinite(res) and res >= 0 else default
            except (TypeError, ValueError):
                return default

        load_ns = _safe_float(result.get("load_duration_ns", 0))
        load_ms = load_ns / 1e6

        tokens = _safe_float(result.get("eval_count", 0))
        eval_ns = _safe_float(result.get("eval_duration_ns", 0))
        eval_seconds = eval_ns / 1e9
        tps = tokens / max(0.001, eval_seconds) if tokens > 0 and eval_seconds > 0 else 0.0

        with self._lock:
            current = self._models.setdefault(
                model,
                {"latency_ms": val_elapsed, "load_ms": load_ms, "tps": tps, "samples": 0.0},
            )
            samples_before = float(current.get("samples", 0.0))
            alpha = self.alpha
            for key, value in (("latency_ms", val_elapsed), ("load_ms", load_ms), ("tps", tps)):
                prev = float(current.get(key, value))
                if not math.isfinite(prev):
                    prev = value
                current[key] = (1 - alpha) * prev + alpha * value
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

