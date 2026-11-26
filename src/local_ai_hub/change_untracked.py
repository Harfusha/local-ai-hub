"""Read-only bounded content identity of untracked files; never follow links."""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path, PurePosixPath
from typing import Any

from .repository_scope import _is_redirecting_link

_MAX_BYTES = 512 * 1024


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        int(info.st_dev), int(info.st_ino), int(info.st_mode), int(info.st_size),
        int(info.st_mtime_ns), int(info.st_ctime_ns),
    )


def observe_untracked(root: str, path: str) -> tuple[dict[str, Any], bytes | None]:
    """Return only a bounded regular-file/link observation plus transient bytes.

    Reject redirecting ancestors and verify the open handle before reading. On
    platforms without directory-fd traversal this is an optimistic read, not
    a sandbox against a malicious concurrent local filesystem administrator.
    """
    relative = PurePosixPath(path)
    if relative.is_absolute() or not relative.parts or any(p in {"..", ".", ".git"} for p in relative.parts):
        raise ValueError("Invalid untracked path")
    if os.name == "nt" and ("\\" in path or ":" in path):
        raise ValueError("Invalid Windows untracked path")
    base = Path(root)
    target = base.joinpath(*relative.parts)
    ancestors = [base]
    for part in relative.parts[:-1]:
        ancestors.append(ancestors[-1] / part)

    def ancestor_ids() -> list[tuple[int, int]]:
        observed = []
        for parent in ancestors:
            info = parent.lstat()
            if _is_redirecting_link(parent) or not stat.S_ISDIR(info.st_mode):
                raise ValueError("Untracked path has a redirecting ancestor")
            observed.append((info.st_dev, info.st_ino))
        return observed

    parents = ancestor_ids()
    initial = target.lstat()
    mode = initial.st_mode
    if stat.S_ISLNK(mode):
        content = os.fsencode(os.readlink(target))
        kind = "symlink"
    elif stat.S_ISREG(mode) and not _is_redirecting_link(target):
        if initial.st_size > _MAX_BYTES:
            raise ValueError("Untracked file exceeds content budget")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(target, flags)
        try:
            current = os.fstat(fd)
            if _identity(current) != _identity(initial) or ancestor_ids() != parents:
                raise ValueError("Untracked file changed before read")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                content = stream.read(_MAX_BYTES + 1)
            if _identity(os.fstat(fd)) != _identity(initial) or len(content) != initial.st_size:
                raise ValueError("Untracked file changed during read")
        finally:
            os.close(fd)
        kind = "regular"
    else:
        raise ValueError("Untracked path is not a regular file or link")
    if len(content) > _MAX_BYTES or _identity(target.lstat()) != _identity(initial) or ancestor_ids() != parents:
        raise ValueError("Untracked observation is unstable or oversized")
    metadata = {
        "content_kind": kind,
        "content_size": len(content),
        "content_digest": hashlib.sha256(content).hexdigest(),
        "observed_mode": stat.S_IMODE(mode),
    }
    return metadata, content if kind == "regular" else None
