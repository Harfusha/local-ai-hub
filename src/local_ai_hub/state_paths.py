from __future__ import annotations

import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

_FALLBACK_LOCK = threading.Lock()
_FALLBACK_BY_PID: dict[int, Path] = {}


def _clean_dir_candidate(raw: Any) -> Path | None:
    if raw is None or isinstance(raw, bool) or not isinstance(raw, (str, Path)):
        return None
    val = str(raw).strip()
    if not val or "\x00" in val:
        return None
    try:
        return Path(val).expanduser()
    except (TypeError, ValueError, OSError):
        return None


def configured_state_dir(config: dict[str, Any] | None, *, create: bool = True) -> Path:
    """Return the configured state directory or a private process-scoped fallback.

    Low-level components are also useful in tests and embedded/library integrations where
    callers may intentionally pass only the subsection they need. Historically those
    partial configurations defaulted to ``Path('.')`` and silently created SQLite files in
    the current checkout. A temporary fallback keeps that convenience without mutating the
    caller's repository. The cache is keyed by the *current* PID so forked children never
    inherit the parent's fallback database path.
    """
    clean_cfg = config if isinstance(config, dict) else {}
    server_cfg = clean_cfg.get("server") if isinstance(clean_cfg.get("server"), dict) else {}
    raw = server_cfg.get("state_dir")
    path = _clean_dir_candidate(raw)
    if path is not None:
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    pid = os.getpid()
    with _FALLBACK_LOCK:
        path = _FALLBACK_BY_PID.get(pid)
        if path is None:
            path = Path(tempfile.mkdtemp(prefix=f"local-ai-hub-{pid}-"))
            try:
                path.chmod(0o700)
            except OSError:
                pass
            _FALLBACK_BY_PID[pid] = path
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def configured_cache_dir(config: dict[str, Any] | None, *, create: bool = True) -> Path:
    """Return the configured cache directory or a cache subdirectory inside state dir."""
    clean_cfg = config if isinstance(config, dict) else {}
    server_cfg = clean_cfg.get("server") if isinstance(clean_cfg.get("server"), dict) else {}
    raw = server_cfg.get("cache_dir")
    path = _clean_dir_candidate(raw)
    if path is not None:
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    state_dir = configured_state_dir(config, create=create)
    cache_dir = state_dir / "cache"
    if create:
        cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_fallback_state_dir(pid: int | None = None) -> Path | None:
    """Return the cached fallback state directory for pid, if one exists."""
    if pid is not None and (isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0):
        return None
    target_pid = os.getpid() if pid is None else int(pid)
    with _FALLBACK_LOCK:
        return _FALLBACK_BY_PID.get(target_pid)


def cleanup_fallback_state_dir(pid: int | None = None) -> bool:
    """Clean up and remove the process fallback state directory for pid."""
    if pid is not None and (isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0):
        return False
    target_pid = os.getpid() if pid is None else int(pid)
    with _FALLBACK_LOCK:
        path = _FALLBACK_BY_PID.pop(target_pid, None)
    if path is None:
        return False
    try:
        shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass
    return True


def clear_all_fallback_state_dirs() -> int:
    """Clean up and remove all cached fallback state directories."""
    with _FALLBACK_LOCK:
        dirs = list(_FALLBACK_BY_PID.values())
        _FALLBACK_BY_PID.clear()
    count = 0
    for path in dirs:
        try:
            shutil.rmtree(path, ignore_errors=True)
            count += 1
        except OSError:
            pass
    return count
