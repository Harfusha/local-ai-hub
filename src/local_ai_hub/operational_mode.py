"""Atomic persistence for the Hub's process-wide operational mode."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


OperationalMode = Literal["active", "gaming", "maintenance"]
_ALLOWED_MODES = frozenset({"active", "gaming", "maintenance"})
_STATE_FILENAME = "operational_mode.json"
_LOCK = threading.RLock()


@dataclass(frozen=True)
class OperationalModeSnapshot:
    mode: OperationalMode
    revision: int
    updated_at: str | None
    degraded: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "revision": self.revision,
            "updated_at": self.updated_at,
            "degraded": self.degraded,
            "error": self.error,
        }


def _state_path(state_dir: str | Path) -> Path:
    return Path(state_dir) / _STATE_FILENAME


def _degraded_snapshot(error: str) -> OperationalModeSnapshot:
    return OperationalModeSnapshot(
        mode="maintenance", revision=0, updated_at=None, degraded=True, error=error
    )


def load_operational_mode(state_dir: str | Path) -> OperationalModeSnapshot:
    """Read the current snapshot; missing state defaults to active, bad state fails closed."""
    path = _state_path(state_dir)
    with _LOCK:
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return OperationalModeSnapshot("active", 0, None)
        except OSError:
            return _degraded_snapshot("operational mode state is unreadable")

        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, UnicodeError):
            return _degraded_snapshot("operational mode state is invalid")
        if not isinstance(value, dict):
            return _degraded_snapshot("operational mode state is invalid")

        mode = value.get("mode")
        revision = value.get("revision")
        updated_at = value.get("updated_at")
        if (
            not isinstance(mode, str)
            or mode not in _ALLOWED_MODES
            or isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 1
            or not isinstance(updated_at, str)
            or not updated_at
        ):
            return _degraded_snapshot("operational mode state is invalid")
        return OperationalModeSnapshot(mode, revision, updated_at)  # type: ignore[arg-type]


def set_operational_mode(state_dir: str | Path, mode: str) -> OperationalModeSnapshot:
    """Persist a new mode by replacing a fully flushed file in the same directory."""
    if not isinstance(mode, str) or mode not in _ALLOWED_MODES:
        raise ValueError("mode must be active, gaming, or maintenance")

    path = _state_path(state_dir)
    with _LOCK:
        prior = load_operational_mode(state_dir)
        snapshot = OperationalModeSnapshot(
            mode=mode,  # type: ignore[arg-type]
            revision=prior.revision + 1,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        payload = json.dumps(snapshot.to_dict(), separators=(",", ":"), sort_keys=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=".operational_mode-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, path)
        except BaseException:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise
        return snapshot


def operational_mode_gate_error(snapshot: OperationalModeSnapshot) -> dict[str, object] | None:
    """Return the stable terminal envelope when agent work is currently blocked."""
    if snapshot.mode == "active" and not snapshot.degraded:
        return None
    return {
        "success": False,
        "error": f"Hub operational mode is {snapshot.mode}; agent tool calls are disabled",
        "error_code": "operational_mode_blocked",
        "operational_mode": snapshot.mode,
        "mode_revision": snapshot.revision,
        "degraded": snapshot.degraded,
        "terminal": True,
        "retryable": False,
    }
