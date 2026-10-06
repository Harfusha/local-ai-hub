from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any


def normalize_changed_paths(root: str | os.PathLike[str], paths: list[str] | tuple[str, ...]) -> list[str]:
    """Return unique project-relative paths, rejecting root escapes."""
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
