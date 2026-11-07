"""State lifecycle management and version enforcement for Local AI Hub.

In v6.0.0, backwards compatibility with legacy pre-v6 state is removed in favor
of a clean-slate architecture. Upgrades from older versions automatically purge
disposable derived state (indexes, caches, telemetry, and stale lockfiles) to ensure
a clean runtime environment without manual intervention.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("local-ai-hub.state-lifecycle")

CURRENT_STATE_VERSION = 6
STATE_VERSION_FILE = "state_version.json"

# Files and directories that are disposable derived runtime state
DISPOSABLE_PATTERNS = (
    "*.sqlite",
    "*.sqlite3",
    "*.sqlite-wal",
    "*.sqlite-shm",
    "*.sqlite3-wal",
    "*.sqlite3-shm",
    "*.lock",
    "*.lock.guard",
    "*.corrupt-*",
    "*.before-rebuild",
    "cache.sqlite*",
    "code-index.sqlite*",
    "preprocess.sqlite*",
    "deterministic.sqlite*",
    "evidence.sqlite*",
    "recovery.sqlite*",
    "rag.sqlite*",
    "telemetry.sqlite*",
    "endpoint_stats.sqlite*",
    "debug_traces.sqlite*",
    "semantic-cache.sqlite*",
    "learning.sqlite*",
    "state.sqlite*",
    "workspace_memory.sqlite*",
    "work_fencing.sqlite*",
    "work_orders.sqlite*",
)

DISPOSABLE_DIRS = {
    "cache",
    "artifacts",
    "backup-rag-512",
    "browser-captures",
    "command-transactions",
    "diagnostics",
    "logs",
    "orphan-archive",
    "rag-fingerprint-mismatch-2026-10-30",
    "rag-fingerprint-mismatch-2026-10-31",
    "test_tmp",
}


def read_state_version(state_dir: Path | str) -> int | None:
    """Read the current state version from state_dir, or None if absent/invalid."""
    path = Path(state_dir) / STATE_VERSION_FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            val = data.get("version")
            if isinstance(val, int):
                return val
    except (OSError, ValueError, TypeError):
        pass
    return None


def write_state_version(
    state_dir: Path | str,
    version: int = CURRENT_STATE_VERSION,
    *,
    migrated_from: int | None = None,
    wiped: bool = False,
) -> Path:
    """Write state_version.json record to state_dir."""
    root = Path(state_dir)
    root.mkdir(parents=True, exist_ok=True)
    target = root / STATE_VERSION_FILE
    payload = {
        "version": version,
        "updated_at": time.time(),
        "migrated_from": migrated_from,
        "clean_slate_wiped": wiped,
    }
    tmp = target.with_name(f"{STATE_VERSION_FILE}.tmp.{os.getpid()}")
    try:
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
    return target


def wipe_disposable_state(state_dir: Path | str) -> dict[str, int]:
    """Purge disposable SQLite databases, caches, and lockfiles from state_dir."""
    root = Path(state_dir)
    if not root.is_dir():
        return {"files_removed": 0, "dirs_removed": 0}

    files_removed = 0
    dirs_removed = 0

    # 1. Remove disposable subdirectories
    for d in list(root.iterdir()):
        try:
            if d.is_dir():
                if d.name in DISPOSABLE_DIRS or d.name.startswith("rag-fingerprint-") or d.name.startswith("backup-"):
                    shutil.rmtree(d, ignore_errors=True)
                    dirs_removed += 1
        except OSError:
            pass

    # 2. Remove disposable files
    for pattern in DISPOSABLE_PATTERNS:
        for f in root.glob(pattern):
            try:
                if f.is_file():
                    f.unlink(missing_ok=True)
                    files_removed += 1
            except OSError:
                pass

    logger.info("Purged disposable state in %s: %d files, %d dirs", root, files_removed, dirs_removed)
    return {"files_removed": files_removed, "dirs_removed": dirs_removed}


def ensure_state_version(
    state_dir: Path | str,
    target_version: int = CURRENT_STATE_VERSION,
    *,
    auto_wipe: bool = True,
) -> dict[str, Any]:
    """Verify that state_dir conforms to target_version.

    If state_version is missing or below target_version and auto_wipe is True,
    disposable legacy state is automatically wiped to guarantee a clean slate.
    """
    root = Path(state_dir)
    root.mkdir(parents=True, exist_ok=True)

    current_ver = read_state_version(root)
    if current_ver == target_version:
        return {"status": "current", "version": target_version, "wiped": False}

    # Check if there is existing state to wipe
    has_existing_state = any(
        item.name != STATE_VERSION_FILE and not item.name.startswith(".hook_")
        for item in root.iterdir()
    )

    wiped = False
    wipe_stats = {"files_removed": 0, "dirs_removed": 0}

    if has_existing_state and auto_wipe:
        logger.warning(
            "State directory version mismatch (found=%s, target=%s). Auto-wiping legacy state for clean slate.",
            current_ver,
            target_version,
        )
        wipe_stats = wipe_disposable_state(root)
        wiped = True

    write_state_version(root, version=target_version, migrated_from=current_ver, wiped=wiped)

    return {
        "status": "upgraded_and_wiped" if wiped else "initialized",
        "version": target_version,
        "previous_version": current_ver,
        "wiped": wiped,
        "stats": wipe_stats,
    }
