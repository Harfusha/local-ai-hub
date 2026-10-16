from __future__ import annotations

import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any


def normalize_changed_paths(
    root: str | os.PathLike[str],
    paths: list[str] | tuple[str, ...] | set[str] | frozenset[str],
) -> list[str]:
    """Return unique project-relative paths, rejecting root escapes."""
    root_path = Path(root).expanduser().resolve(strict=False)
    if not root_path.is_dir():
        raise ValueError(f"root directory does not exist: {root}")
    if not isinstance(paths, (list, tuple, set, frozenset)) or not paths:
        raise ValueError("changed paths must be a non-empty list or set")
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
        self.debounce_seconds = max(0.0, min(30.0, float(cfg.get("debounce_seconds", 1.0))))
        self.max_paths = max(1, min(256, int(cfg.get("max_paths", 64))))
        self.max_tracked_roots = max(1, min(1024, int(cfg.get("max_tracked_roots", 128))))
        self._lock = threading.RLock()
        self._root_jobs: OrderedDict[tuple[str, str], str] = OrderedDict()

    def submit(
        self,
        tenant: str,
        root: str,
        paths: list[str] | tuple[str, ...] | set[str] | frozenset[str],
        command: str = "",
    ) -> dict[str, Any]:
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
        ordered_paths = sorted(paths) if isinstance(paths, (set, frozenset)) else paths
        normalized_paths = normalize_changed_paths(normalized_root, list(ordered_paths)[: self.max_paths])
        key = (tenant, os.path.normcase(normalized_root))
        with self._lock:
            previous = self._root_jobs.get(key)
            if previous:
                self.async_jobs.cancel(tenant, previous)
            result = self.async_jobs.submit(
                tenant,
                "speculative_lint",
                {"root": normalized_root, "paths": normalized_paths, "command": str(command or "")[:4000]},
                dispatch_delay_seconds=self.debounce_seconds,
            )
            if result.get("job_id"):
                self._root_jobs[key] = str(result["job_id"])
                self._root_jobs.move_to_end(key)
                while len(self._root_jobs) > self.max_tracked_roots:
                    self._root_jobs.popitem(last=False)
        result.update({"read_only": True, "auto_fix": False, "paths": normalized_paths, "debounce_seconds": self.debounce_seconds})
        return result

    def status(self, tenant: str, job_id: str) -> dict[str, Any]:
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError("job_id cannot be empty")
        return self.async_jobs.status(tenant, job_id)

    def cancel(self, tenant: str, job_id: str) -> dict[str, Any]:
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError("job_id cannot be empty")
        result = self.async_jobs.cancel(tenant, job_id)
        if isinstance(result, dict) and result.get("success") is True:
            with self._lock:
                for key, tracked_job_id in tuple(self._root_jobs.items()):
                    if key[0] == tenant and tracked_job_id == job_id:
                        self._root_jobs.pop(key, None)
        return result
