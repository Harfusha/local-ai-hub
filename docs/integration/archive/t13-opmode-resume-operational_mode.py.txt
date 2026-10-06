"""Persist and enforce lightweight Hub operating modes."""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


MODE_STATE_FILENAME = "operational_mode.json"
OperationalModeName = Literal["active", "gaming", "maintenance"]
OperationClass = Literal["deterministic_read", "inference", "preprocess"]
_MODES = frozenset({"active", "gaming", "maintenance"})
_OPERATIONS = frozenset({"deterministic_read", "inference", "preprocess"})


@dataclass(frozen=True)
class OperationalMode:
    mode: OperationalModeName
    degraded: bool = False
    reason: str = ""
    updated_at: float = 0.0


def _state_path(state_dir: str | os.PathLike[str]) -> Path:
    return Path(state_dir) / MODE_STATE_FILENAME


def load_operational_mode(state_dir: str | os.PathLike[str]) -> OperationalMode:
    """Read mode without creating state. Missing state preserves legacy active mode."""
    path = _state_path(state_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return OperationalMode(mode="active")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return OperationalMode(mode="maintenance", degraded=True, reason=f"invalid mode state: {type(exc).__name__}")
    if not isinstance(data, dict) or data.get("mode") not in _MODES:
        return OperationalMode(mode="maintenance", degraded=True, reason="invalid mode state")
    try:
        updated_at = float(data.get("updated_at", 0.0) or 0.0)
    except (TypeError, ValueError, OverflowError):
        return OperationalMode(mode="maintenance", degraded=True, reason="invalid mode timestamp")
    if not math.isfinite(updated_at):
        return OperationalMode(mode="maintenance", degraded=True, reason="invalid mode timestamp")
    return OperationalMode(
        mode=data["mode"],
        degraded=bool(data.get("degraded", False)),
        reason=str(data.get("reason", ""))[:240],
        updated_at=updated_at,
    )


def set_operational_mode(state_dir: str | os.PathLike[str], mode: str) -> OperationalMode:
    normalized = str(mode).strip().lower()
    if normalized not in _MODES:
        raise ValueError(f"unsupported operational mode: {mode}")
    state = OperationalMode(mode=normalized, updated_at=time.time())
    path = _state_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump({"mode": state.mode, "updated_at": state.updated_at}, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return state


def mode_allows(state: OperationalMode | str, operation: str) -> bool:
    if operation not in _OPERATIONS:
        raise ValueError(f"unknown operation class: {operation}")
    if isinstance(state, OperationalMode) and state.degraded:
        return operation == "deterministic_read"
    mode = state if isinstance(state, str) else state.mode
    if mode not in _MODES:
        return operation == "deterministic_read"
    if mode == "active":
        return True
    return operation == "deterministic_read"


def blocked_operation(state: OperationalMode, operation: OperationClass) -> dict[str, object]:
    return {
        "success": False,
        "blocked": True,
        "operation": operation,
        "operational_mode": state.mode,
        "degraded": state.degraded,
        "error": f"{operation} blocked while operational mode is {state.mode}",
        "terminal": True,
        "retryable": False,
    }
