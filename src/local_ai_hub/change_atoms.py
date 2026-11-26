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

from .change_semantics import summarize_python_patch

_MAX_PATCH_BYTES = 512 * 1024
_MAX_PATCHES = 64
_MAX_LINES = 10000
_MAX_HUNKS = 64
_CACHE_SIZE = 256
_HunkRow = tuple[int, int, int, int, str]
_CacheValue = tuple[tuple[_HunkRow, ...], int]
_CACHE: OrderedDict[str, _CacheValue] = OrderedDict()
_LOCK = threading.Lock()
_HUNK = re.compile(rb"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: |$)")


def identity(*parts: str) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def _decode_cache(value: Any) -> _CacheValue | None:
    if not isinstance(value, dict) or value.get("schema") != 2:
        return None
    rows, count = value.get("rows"), value.get("count")
    if (
        not isinstance(rows, list) or type(count) is not int
        or not 0 <= count <= _MAX_LINES
        or len(rows) != min(count, _MAX_HUNKS)
    ):
        return None
    decoded = []
    for row in rows:
        if (
            not isinstance(row, list) or len(row) != 5
            or any(type(n) is not int or n < 0 for n in row[:4])
            or not isinstance(row[4], str) or re.fullmatch(r"[0-9a-f]{64}", row[4]) is None
        ):
            return None
        decoded.append((row[0], row[1], row[2], row[3], row[4]))
    return tuple(decoded), count


def _remember(key: str, value: _CacheValue) -> None:
    with _LOCK:
        _CACHE[key] = value
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_SIZE:
            _CACHE.popitem(last=False)


def _hunks(
    patch: bytes, key: str, *, persistent_cache: Any | None = None,
) -> tuple[tuple[_HunkRow, ...], int, str]:
    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            _CACHE.move_to_end(key)
            return cached[0], cached[1], "memory"

    if persistent_cache is not None:
        cached = _decode_cache(persistent_cache.get(key))
        if cached is not None:
            _remember(key, cached)
            return cached[0], cached[1], "persistent"

    # Include exact header and body in the digest. An unrelated hunk at another
    # location does not invalidate this one; offset changes conservatively do.
    lines = patch.split(b"\n")
    ranges = []
    count = 0
    header: tuple[int, int, int, int] | None = None
    digest: Any = None

    def finish() -> None:
        if header is not None and digest is not None:
            ranges.append((*header, digest.hexdigest()))

    for line in lines:
        match = _HUNK.match(line)
        if match:
            finish()
            header = None
            digest = None
            count += 1
            if count <= _MAX_HUNKS:
                old, old_count, new, new_count = match.groups()
                header = (int(old), int(old_count or b"1"), int(new), int(new_count or b"1"))
                digest = hashlib.sha256()
        if digest is not None:
            digest.update(line)
            digest.update(b"\n")
    finish()
    value = (tuple(ranges), count)
    _remember(key, value)
    if persistent_cache is not None:
        persistent_cache.set(key, {"schema": 2, "rows": [list(row) for row in ranges], "count": count})
    return value[0], value[1], "computed"


def inspect_change_atoms(
    root: str,
    statuses: dict[str, str],
    staged: dict[str, tuple[int | None, int | None]],
    unstaged: dict[str, tuple[int | None, int | None]],
    git: Callable[..., bytes],
    *,
    persistent_cache: Any | None = None,
    staged_scope: str = "staged",
) -> dict[str, Any]:
    """Inspect tracked textual patches twice and publish only matched observations.

    No raw patch or source lines are retained in the cache or returned. Limits
    apply to analysis, not to the subprocess transport's stdout allocation.
    """
    observations: dict[str, list[dict[str, Any]]] = {}
    unavailable: list[dict[str, str]] = []
    pending: list[tuple[str, str, tuple[str, ...], str]] = []
    cache_hits = 0
    persistent_hits = 0
    semantic_attempts = 0
    deadline = time.monotonic() + 10
    for path, xy in sorted(statuses.items()):
        if xy == "??" or xy in {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}:
            unavailable.append({"path": path, "scope": "worktree", "reason": "untracked_or_conflicted"})
            continue
        for scope, changes, flag in ((staged_scope, staged, xy[0]), ("unstaged", unstaged, xy[1])):
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
                *(("--cached",) if scope == staged_scope else ()),
                "--", ":(literal)" + path,
            )
            patch = git(*args)
            if not patch or len(patch) > _MAX_PATCH_BYTES or b"\nSubmodule " in patch or b"Subproject commit " in patch:
                unavailable.append({"path": path, "scope": scope, "reason": "unsupported_or_large_patch"})
                continue
            digest = hashlib.sha256(patch).hexdigest()
            atom_id = identity("patch-v1", root, path, scope, digest)
            ranges, count, source = _hunks(
                patch, identity("hunk-summary-v2", atom_id), persistent_cache=persistent_cache,
            )
            cache_hits += int(source != "computed")
            persistent_hits += int(source == "persistent")
            semantic = {"status": "unavailable", "reason": "unsupported_language"}
            if path.lower().endswith(".py"):
                if semantic_attempts < 8 and time.monotonic() < deadline:
                    semantic_attempts += 1
                    semantic = summarize_python_patch(
                        patch, git, cache=persistent_cache,
                        key=identity("python-ast-summary-v1", atom_id),
                    )
                else:
                    semantic = {"status": "unavailable", "reason": "analysis_budget"}
            observations.setdefault(path, []).append({
                "semantic": semantic,
                "atom_id": atom_id,
                "scope": scope,
                "hunk_count": count,
                "hunks": [
                    {
                        "old_start": a, "old_count": b, "new_start": c, "new_count": d,
                        "hunk_id": identity("hunk-v1", root, path, scope, digest),
                    }
                    for a, b, c, d, digest in ranges
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
        "persistent_cache_hits": persistent_hits,
    }
