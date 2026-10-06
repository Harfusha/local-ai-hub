"""Atomic persistence for the Hub's process-wide operational mode."""

from __future__ import annotations

import json
import errno
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal


OperationalMode = Literal["active", "gaming", "maintenance"]
_ALLOWED_MODES = frozenset({"active", "gaming", "maintenance"})
_STATE_FILENAME = "operational_mode.json"
_LOCK_FILENAME = "operational_mode.lock"
_LOCK = threading.RLock()
_WRITER_LOCK_TIMEOUT_SECONDS = 5.0
_REPLACE_RETRY_SECONDS = 1.0


@contextmanager
def _state_writer_lock(state_dir: str | Path) -> Iterator[None]:
    """Serialize state updates across Hub, MCP, and CLI processes."""
    lock_path = Path(state_dir) / _LOCK_FILENAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        deadline = time.monotonic() + _WRITER_LOCK_TIMEOUT_SECONDS
        if os.name == "nt":
            import msvcrt

            while True:
                try:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if getattr(exc, "winerror", None) not in {33, 36} and exc.errno not in {errno.EACCES, errno.EDEADLK, errno.EAGAIN}:
                        raise
                    if time.monotonic() >= deadline:
                        raise TimeoutError("timed out waiting for operational mode writer lock") from exc
                    time.sleep(0.02)
        else:
            import fcntl

            while True:
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError as exc:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("timed out waiting for operational mode writer lock") from exc
                    time.sleep(0.02)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _replace_state_file(source: str, destination: Path) -> None:
    deadline = time.monotonic() + _REPLACE_RETRY_SECONDS
    while True:
        try:
            os.replace(source, destination)
            return
        except OSError as exc:
            windows_lock_conflict = getattr(exc, "winerror", None) in {32, 33}
            if not isinstance(exc, PermissionError) and not windows_lock_conflict:
                raise
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.02)


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
        except UnicodeError:
            return _degraded_snapshot("operational mode state is invalid")

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
    with _LOCK, _state_writer_lock(state_dir):
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
            _replace_state_file(temporary_name, path)
        except BaseException:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise
        return snapshot


def operational_mode_gate_error(
    snapshot: OperationalModeSnapshot | None,
    action: str = "",
    *,
    requires_heavy_work: bool = True,
) -> dict[str, object] | None:
    """Return a bounded, retryable pause response when work is temporarily gated."""
    if snapshot is not None and snapshot.mode == "active" and not snapshot.degraded:
        return None
    mode = snapshot.mode if snapshot is not None else "maintenance"
    degraded = snapshot is None or snapshot.degraded
    safe_job_actions = {"status", "wait", "result", "cancel", "evaluation_report"}
    if not degraded and mode == "gaming" and action.strip().lower().replace("-", "_") in safe_job_actions:
        return None
    if not degraded and mode == "gaming" and not requires_heavy_work:
        return None
    return {
        "success": False,
        "mode": mode,
        "error": f"hub paused: {mode} mode active",
        "terminal": False,
        "retryable": True,
        "retry_after_seconds": 5,
    }
