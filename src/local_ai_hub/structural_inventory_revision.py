"""Bounded inventory metadata revisions for structural-search pagination."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Callable


_SUFFIXES = (".py", ".php", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".cs")


def source_inventory_revision(
    root: Path,
    pattern: str,
    path: Path | None,
    ignore_dirs: set[str],
    *,
    is_symlink_or_reparse_point: Callable[[Path], bool],
) -> str | None:
    """Hash source path/identity metadata; return None when verification fails.

    This detects normal editor saves, inserts and deletions across pages.
    Metadata-preserving rewrites require an immutable checkout for strict
    cross-request consistency. No source bytes are loaded for the inventory.
    """
    digest = hashlib.sha256()
    digest.update(b"structural-inventory-v1\0")
    digest.update(os.fsencode(str(root)))
    digest.update(b"\0")
    digest.update(pattern.encode("utf-8", errors="replace"))
    digest.update(b"\0")
    digest.update(os.fsencode(path.relative_to(root).as_posix()) if path is not None else b"*")
    count = 0
    failed = False

    def feed(candidate: Path) -> bool:
        nonlocal count
        count += 1
        if count > 100_401:
            return False
        try:
            item = candidate.stat(follow_symlinks=False)
            rel = os.fsencode(candidate.relative_to(root).as_posix())
            stat_fields = (
                item.st_mode, item.st_dev, item.st_ino, item.st_size,
                item.st_mtime_ns, item.st_ctime_ns,
                int(getattr(item, "st_file_attributes", 0)),
            )
            digest.update(len(rel).to_bytes(4, "big"))
            digest.update(rel)
            digest.update(repr(stat_fields).encode("ascii"))
            digest.update(b"\0")
            return True
        except (OSError, RuntimeError, ValueError):
            return False

    if path is not None:
        return digest.hexdigest() if feed(path) else None

    def onerror(_error: OSError) -> None:
        nonlocal failed
        failed = True

    for current_root, dirs, filenames in os.walk(root, onerror=onerror):
        dirs.sort()
        kept_dirs: list[str] = []
        for dirname in dirs:
            if dirname in ignore_dirs or dirname.startswith("."):
                continue
            candidate = Path(current_root) / dirname
            if not feed(candidate):
                return None
            try:
                if not is_symlink_or_reparse_point(candidate):
                    kept_dirs.append(dirname)
            except (OSError, ValueError):
                return None
        dirs[:] = kept_dirs
        for filename in sorted(filenames):
            if filename.endswith(_SUFFIXES) and not feed(Path(current_root) / filename):
                return None
        if failed:
            return None
    return digest.hexdigest() if not failed else None
