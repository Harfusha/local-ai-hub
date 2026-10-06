from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path
from typing import Any

_FALLBACK_LOCK = threading.Lock()
_FALLBACK_BY_PID: dict[int, Path] = {}


def configured_state_dir(config: dict[str, Any] | None, *, create: bool = True) -> Path:
    """Return the configured state directory or a private process-scoped fallback.

    Low-level components are also useful in tests and embedded/library integrations where
    callers may intentionally pass only the subsection they need. Historically those
    partial configurations defaulted to ``Path('.')`` and silently created SQLite files in
    the current checkout. A temporary fallback keeps that convenience without mutating the
    caller's repository. The cache is keyed by the *current* PID so forked children never
    inherit the parent's fallback database path.
    """
    raw = ((config or {}).get("server", {}) or {}).get("state_dir")
    if raw is not None and str(raw).strip():
        path = Path(str(raw)).expanduser()
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
