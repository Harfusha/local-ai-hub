"""Content-addressed, metadata-only summaries of observed tracked Git patches.

A patch identity is not a worktree receipt, ownership proof or commit lease.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

_MAX_PATCH_BYTES = 512 * 1024
_MAX_PATCHES = 64
_MAX_LINES = 10000
_MAX_HUNKS = 64
_CACHE_SIZE = 256
_CACHE: OrderedDict[str, tuple[tuple[tuple[int, int, int, int], ...], int]] = OrderedDict()
_LOCK = threading.Lock()
_HUNK = re.compile(rb"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: |$)")


def identity(*parts: str) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def _hunks(patch: bytes, key: str) -> tuple[tuple[tuple[int, int, int, int], ...], int, bool]:
    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            _CACHE.move_to_end(key)
            return cached[0], cached[1], True

    ranges = []
    count = 0
    for line in patch.split(b"\n"):
        match = _HUNK.match(line)
        if match:
            count += 1
            if len(ranges) < _MAX_HUNKS:
                old, old_count, new, new_count = match.groups()
                ranges.append((int(old), int(old_count or b"1"), int(new), int(new_count or b"1")))
    value = (tuple(ranges), count)
    with _LOCK:
        _CACHE[key] = value
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_SIZE:
            _CACHE.popitem(last=False)
    return value[0], value[1], False


def inspect_change_atoms(
    root: str,
    statuses: dict[str, str],
    staged: dict[str, tuple[int | None, int | None]],
    unstaged: dict[str, tuple[int | None, int | None]],
    git: Callable[..., bytes],
) -> dict[str, Any]:
    """Inspect tracked textual patches twice and publish only matched observations.

    No raw patch or source lines are retained in the cache or returned. Limits
    apply to analysis, not to the subprocess transport's stdout allocation.
    """
    observations: dict[str, list[dict[str, Any]]] = {}
    unavailable: list[dict[str, str]] = []
    pending: list[tuple[str, str, tuple[str, ...], str]] = []
    cache_hits = 0
    deadline = time.monotonic() + 10
    for path, xy in sorted(statuses.items()):
        if xy == "??" or xy in {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}:
            unavailable.append({"path": path, "scope": "worktree", "reason": "untracked_or_conflicted"})
            continue
        for scope, changes, flag in (("staged", staged, xy[0]), ("unstaged", unstaged, xy[1])):
            if flag == " ":
                continue
            counts = changes.get(path)
            if counts is None or any(n is None for n in counts):
                unavailable.append({"path": path, "scope": scope, "reason": "non_text_or_missing_numstat"})
                continue
            if sum(n for n in counts if n is not None) > _MAX_LINES or len(pending) >= _MAX_PATCHES or time.monotonic() >= deadline:
                unavailable.append({"path": path, "scope": scope, "reason": "analysis_budget"})
                continue
            args = (
                "diff", "--patch", "--full-index", "--no-renames", "--no-ext-diff",
                "--no-textconv", "--no-color", "--unified=0", "--no-indent-heuristic",
                "--diff-algorithm=myers", "--submodule=short", "--ignore-submodules=none",
                *(("--cached",) if scope == "staged" else ()),
                "--", ":(literal)" + path,
            )
            patch = git(*args)
            if not patch or len(patch) > _MAX_PATCH_BYTES or b"\nSubmodule " in patch or b"Subproject commit " in patch:
                unavailable.append({"path": path, "scope": scope, "reason": "unsupported_or_large_patch"})
                continue
            digest = hashlib.sha256(patch).hexdigest()
            atom_id = identity("patch-v1", root, path, scope, digest)
            ranges, count, reused = _hunks(patch, atom_id)
            cache_hits += int(reused)
            observations.setdefault(path, []).append({
                "atom_id": atom_id,
                "scope": scope,
                "hunk_count": count,
                "hunks": [
                    {"old_start": a, "old_count": b, "new_start": c, "new_count": d}
                    for a, b, c, d in ranges
                ],
                "hunks_truncated": count > len(ranges),
            })
            pending.append((path, scope, args, digest))

    # Re-read selected patches to detect content edits that preserve status and
    # line counts. This is optimistic observation, not a filesystem lock.
    for path, scope, args, digest in pending:
        if time.monotonic() >= deadline:
            observations[path] = [item for item in observations[path] if item["scope"] != scope]
            unavailable.append({"path": path, "scope": scope, "reason": "recheck_budget"})
            continue
        if hashlib.sha256(git(*args)).hexdigest() != digest:
            raise ValueError("Git patch changed during inspection")

    return {
        "observations": observations,
        "unavailable": unavailable,
        "cache_hits": cache_hits,
    }
