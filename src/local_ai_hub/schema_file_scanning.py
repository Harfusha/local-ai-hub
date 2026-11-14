from __future__ import annotations

import os
import time
from pathlib import Path


_SKIP_SCHEMA_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", "state", "artifacts",
    "test", "tests", "__tests__", "fixture", "fixtures", "tool-envs",
}


def scan_schema_files(
    root: Path,
    *,
    suffix: str,
    deadline: float,
    migrations_only: bool,
    max_dirs: int,
    max_entries: int,
    max_files: int,
) -> list[Path]:
    """Collect schema candidates without materializing unbounded directory listings."""
    canonical_root = root.resolve(strict=True)
    pending = [canonical_root]
    candidates: list[Path] = []
    visited_dirs = 0
    visited_entries = 0
    visited_canonical_dirs: set[Path] = set()

    while pending:
        current = pending.pop().resolve(strict=True)
        _ensure_within_root(current, canonical_root, "schema scan directory")
        if current in visited_canonical_dirs:
            continue
        visited_canonical_dirs.add(current)
        visited_dirs += 1
        if visited_dirs > max_dirs or time.monotonic() >= deadline:
            raise TimeoutError("schema scan exceeded its directory or time budget")

        with os.scandir(current) as entries:
            for entry in entries:
                visited_entries += 1
                if visited_entries > max_entries or time.monotonic() >= deadline:
                    raise TimeoutError("schema scan exceeded its entry or time budget")
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if getattr(os.path, "isjunction", lambda _path: False)(entry.path):
                        resolved_child = Path(entry.path).resolve(strict=True)
                        _ensure_within_root(resolved_child, canonical_root, "schema scan junction")
                    if entry.name.lower() not in _SKIP_SCHEMA_DIRS and not entry.name.startswith("."):
                        pending.append(Path(entry.path))
                        if len(pending) + visited_dirs > max_dirs:
                            raise TimeoutError("schema scan exceeded its directory budget")
                    continue
                if not entry.is_file(follow_symlinks=False) or not entry.name.lower().endswith(suffix):
                    continue
                candidate = current / entry.name
                if migrations_only and not any(
                    part.lower() in {"migration", "migrations"}
                    for part in candidate.parent.relative_to(root).parts
                ):
                    continue
                candidates.append(candidate)
                if len(candidates) > max_files:
                    raise TimeoutError(f"schema scan exceeded {max_files} files")

    return sorted(candidates)


def _ensure_within_root(path: Path, root: Path, subject: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise PermissionError(f"{subject} resolves outside the requested root") from exc
