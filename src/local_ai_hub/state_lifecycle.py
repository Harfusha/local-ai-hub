"""State version checks for Local AI Hub.

Runtime startup never deletes or migrates existing state. A version mismatch
requires an explicit offline conversion with backup and preservation checks.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

CURRENT_STATE_VERSION = 6
STATE_VERSION_FILE = "state_version.json"

def read_state_version(state_dir: Path | str) -> int | None:
    """Read the current state version from state_dir, or None if absent/invalid."""
    path = Path(state_dir) / STATE_VERSION_FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            val = data.get("version")
            if type(val) is int and val > 0:
                return val
    except (OSError, ValueError, TypeError):
        pass
    return None


def write_state_version(
    state_dir: Path | str,
    version: int = CURRENT_STATE_VERSION,
    *,
    migrated_from: int | None = None,
) -> Path:
    """Write state_version.json record to state_dir."""
    root = Path(state_dir)
    root.mkdir(parents=True, exist_ok=True)
    target = root / STATE_VERSION_FILE
    payload = {
        "version": version,
        "updated_at": time.time(),
        "migrated_from": migrated_from,
        "clean_slate_wiped": False,
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


def ensure_state_version(
    state_dir: Path | str,
    target_version: int = CURRENT_STATE_VERSION,
) -> dict[str, Any]:
    """Verify or initialize the marker without deleting or migrating state.

    Existing data under another or unknown version stops startup. Callers must
    complete a separately backed-up, verified offline conversion first.
    """
    root = Path(state_dir)
    if type(target_version) is not int or target_version < 1:
        raise ValueError("target_version must be a positive integer")
    root.mkdir(parents=True, exist_ok=True)

    current_ver = read_state_version(root)
    if current_ver == target_version:
        return {"status": "current", "version": target_version, "wiped": False}

    if current_ver is not None and current_ver > target_version:
        raise RuntimeError(
            f"State version {current_ver} is newer than supported version {target_version}; "
            "refusing startup to preserve state. Use an offline state conversion before retrying."
        )

    has_existing_state = any(item.name != STATE_VERSION_FILE for item in root.iterdir())
    if has_existing_state:
        raise RuntimeError(
            f"State version mismatch (found={current_ver}, target={target_version}); "
            "refusing to delete or migrate state. Complete an offline state conversion "
            "with backup and verified record preservation before startup."
        )

    write_state_version(root, version=target_version, migrated_from=current_ver)

    return {
        "status": "initialized",
        "version": target_version,
        "previous_version": current_ver,
        "wiped": False,
    }
