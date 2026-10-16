from __future__ import annotations

import math
import os
import threading
from pathlib import Path
from typing import Any


def _safe_int(val: Any, default: int, min_val: int | None = None, max_val: int | None = None) -> int:
    if isinstance(val, bool) or val is None:
        return default
    try:
        if isinstance(val, float) and not math.isfinite(val):
            return default
        res = int(val)
    except (ValueError, TypeError, OverflowError):
        return default
    if min_val is not None and res < min_val:
        return min_val
    if max_val is not None and res > max_val:
        return max_val
    return res


def _safe_float(val: Any, default: float, min_val: float | None = None, max_val: float | None = None) -> float:
    if isinstance(val, bool) or val is None:
        return default
    try:
        res = float(val)
        if not math.isfinite(res):
            return default
    except (ValueError, TypeError, OverflowError):
        return default
    if min_val is not None and res < min_val:
        return min_val
    if max_val is not None and res > max_val:
        return max_val
    return res


def normalize_changed_paths(root: str | os.PathLike[str], paths: list[str] | tuple[str, ...]) -> list[str]:
    """Return unique project-relative paths, rejecting root escapes."""
    if not isinstance(root, (str, os.PathLike)) or "\x00" in str(root):
        raise ValueError("root directory cannot contain null bytes")
    root_path = Path(root).expanduser().resolve(strict=False)
    if not root_path.is_dir():
        raise ValueError(f"root directory does not exist: {root}")
    if not isinstance(paths, (list, tuple)) or not paths:
        raise ValueError("changed paths must be a non-empty list")
    normalized: set[str] = set()
    for raw in paths:
        value = str(raw or "").strip()
        if not value:
            continue
        if "\x00" in value:
            raise ValueError("changed path cannot contain null bytes")
        candidate = (root_path / value).resolve(strict=False) if not Path(value).is_absolute() else Path(value).expanduser().resolve(strict=False)
        try:
            relative = candidate.relative_to(root_path)
        except ValueError as exc:
            raise ValueError(f"changed path must remain within root: {value}") from exc
        if relative == Path("."):
            raise ValueError("changed path must name a file")
        normalized.add(relative.as_posix())
    if not normalized:
        raise ValueError("changed paths must contain at least one non-empty path")
    return sorted(normalized)


class SpeculativeLintQueue:
    """Opt-in debounce/cancellation facade over durable async jobs."""

    def __init__(self, async_jobs: Any, config: dict[str, Any]):
        self.async_jobs = async_jobs
        cfg = config.get("speculative_lint", {}) if isinstance(config, dict) else {}
        self.enabled = bool(cfg.get("enabled", False))
        self.debounce_seconds = _safe_float(cfg.get("debounce_seconds"), 1.0, min_val=0.0, max_val=30.0)
        self.max_paths = _safe_int(cfg.get("max_paths"), 64, min_val=1, max_val=256)
        self._lock = threading.RLock()
        self._root_jobs: dict[str, str] = {}

    def submit(self, tenant: str, root: str, paths: list[str] | tuple[str, ...], command: str = "") -> dict[str, Any]:
        if not self.enabled:
            return {
                "success": False,
                "unsupported": True,
                "feature": "speculative_lint",
                "error": "speculative lint is disabled (speculative_lint.enabled=false)",
                "terminal": True,
                "retryable": False,
            }
        normalized_root = str(Path(root).expanduser().resolve(strict=False))
        normalized_paths = normalize_changed_paths(normalized_root, list(paths)[: self.max_paths])
        with self._lock:
            previous = self._root_jobs.get(normalized_root)
            if previous:
                self.async_jobs.cancel(tenant, previous)
            result = self.async_jobs.submit(
                tenant,
                "speculative_lint",
                {"root": normalized_root, "paths": normalized_paths, "command": str(command or "")[:4000]},
                dispatch_delay_seconds=self.debounce_seconds,
            )
            if result.get("job_id"):
                self._root_jobs[normalized_root] = str(result["job_id"])
        result.update({"read_only": True, "auto_fix": False, "paths": normalized_paths, "debounce_seconds": self.debounce_seconds})
        return result

    def status(self, tenant: str, job_id: str) -> dict[str, Any]:
        return self.async_jobs.status(tenant, str(job_id or ""))

    def cancel(self, tenant: str, job_id: str) -> dict[str, Any]:
        return self.async_jobs.cancel(tenant, str(job_id or ""))

    def is_enabled(self) -> bool:
        return bool(self.enabled)

    def active_roots(self) -> list[str]:
        with self._lock:
            return sorted(self._root_jobs.keys())

    def clear(self) -> None:
        with self._lock:
            self._root_jobs.clear()
