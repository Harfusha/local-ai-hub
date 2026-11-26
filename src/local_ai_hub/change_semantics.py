"""Bounded structural summaries of exact Git blobs, without source retention."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from typing import Any

from .ast_diff import ast_diff

_INDEX = re.compile(rb"^index ([0-9a-f]{40,64})\.\.([0-9a-f]{40,64})(?: [0-7]{6})?$", re.MULTILINE)
_MAX_SOURCE = 256 * 1024
_MAX_SYMBOLS = 24
_KINDS = {"added", "removed", "modified", "renamed", "moved", "reordered", "module_modified"}


_HUNK = re.compile(rb"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: |$)")


def _blob_matches(content: bytes, oid: str) -> bool:
    algorithm = "sha1" if len(oid) == 40 else "sha256" if len(oid) == 64 else ""
    if not algorithm:
        return False
    return hashlib.new(algorithm, b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest() == oid


def _lines(content: bytes) -> list[bytes]:
    parts = content.split(b"\n")
    return [p + b"\n" for p in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def reconstruct_blob(before: bytes, patch: bytes, oid: str) -> bytes | None:
    """Apply an observed unified patch in memory; trust only the resulting Git hash."""
    source = _lines(before)
    patch_lines = _lines(patch)
    output: list[bytes] = []
    cursor = 0
    i = 0
    while i < len(patch_lines) and not patch_lines[i].startswith(b"@@ "):
        i += 1
    if i == len(patch_lines):
        return before if _blob_matches(before, oid) else None
    while i < len(patch_lines):
        match = _HUNK.match(patch_lines[i].rstrip(b"\n"))
        if match is None:
            return None
        old, old_count, new, new_count = match.groups()
        old_n, new_n = int(old_count or b"1"), int(new_count or b"1")
        old_at = int(old) - (1 if old_n else 0)
        new_at = int(new) - (1 if new_n else 0)
        if not cursor <= old_at <= len(source):
            return None
        output.extend(source[cursor:old_at])
        cursor = old_at
        if len(output) != new_at:
            return None
        i += 1
        removed = added = 0
        while i < len(patch_lines) and not patch_lines[i].startswith(b"@@ "):
            row = patch_lines[i]
            if not row or row[:1] not in {b" ", b"-", b"+"}:
                return None
            flag, content = row[:1], row[1:]
            i += 1
            if i < len(patch_lines) and patch_lines[i] == b"\\ No newline at end of file\n":
                if not content.endswith(b"\n"):
                    return None
                content = content[:-1]
                i += 1
            if flag in {b" ", b"-"}:
                if cursor >= len(source) or source[cursor] != content:
                    return None
                cursor += 1
                removed += 1
            if flag in {b" ", b"+"}:
                output.append(content)
                added += 1
        if (removed, added) != (old_n, new_n):
            return None
    output.extend(source[cursor:])
    result = b"".join(output)
    if len(result) > _MAX_SOURCE or not _blob_matches(result, oid):
        return None
    return result


def summarize_python_patch(
    patch: bytes, git: Callable[..., bytes], *, cache: Any | None = None, key: str,
) -> dict[str, Any]:
    """Summarize only full object identities that Git can actually resolve.

    Missing unstaged blobs are reconstructed from the observed patch and
    verified against their full Git object ID; no filesystem read or write.
    """
    match = _INDEX.search(patch)
    if match is None:
        return {"status": "unavailable", "reason": "no_blob_pair"}
    if cache is not None:
        stored = cache.get(key)
        if _valid(stored):
            return stored
    sources: list[bytes] = []
    for side, raw in enumerate(match.groups()):
        oid = raw.decode("ascii")
        if len(oid) not in {40, 64}:
            return {"status": "unavailable", "reason": "unsupported_object_id"}
        if not oid.strip("0"):
            sources.append(b"")
            continue
        try:
            object_type = git("cat-file", "-t", oid).strip()
        except ValueError:
            object_type = b"missing"
        if object_type == b"missing" and side == 1:
            content = reconstruct_blob(sources[0], patch, oid)
            if content is None:
                return {"status": "unavailable", "reason": "patch_reconstruction_failed"}
            sources.append(content)
            continue
        if object_type != b"blob":
            return {"status": "unavailable", "reason": "not_blob"}
        try:
            size = int(git("cat-file", "-s", oid).strip())
            if not 0 <= size <= _MAX_SOURCE:
                return {"status": "unavailable", "reason": "source_budget"}
            content = git("cat-file", "blob", oid)
            if len(content) != size or not _blob_matches(content, oid):
                return {"status": "unavailable", "reason": "blob_hash_mismatch"}
            sources.append(content)
        except ValueError:
            return {"status": "unavailable", "reason": "blob_unavailable"}
    return summarize_python_sources(*sources, cache=cache, key=key)


def summarize_python_sources(
    before: bytes, after: bytes, *, cache: Any | None = None, key: str,
) -> dict[str, Any]:
    if max(len(before), len(after)) > _MAX_SOURCE:
        return {"status": "unavailable", "reason": "source_budget"}
    if cache is not None:
        stored = cache.get(key)
        if _valid(stored):
            return stored
    try:
        decoded = [before.decode("utf-8"), after.decode("utf-8")]
    except UnicodeError:
        return {"status": "unavailable", "reason": "non_utf8_source"}
    result = ast_diff(*decoded)
    if not result.get("success"):
        return {"status": "unavailable", "reason": "ast_analysis_failed"}
    symbols = []
    for change in result["changes"][:_MAX_SYMBOLS]:
        loc = change["after"] or change["before"]
        symbols.append({
            "symbol": loc["qualified_name"][:200] if loc else "<module>",
            "types": change["change_types"],
        })
    summary = {
        "status": "observed",
        "method": "python_ast_v1",
        "structural_equal": result["structural_equal"],
        "formatting_only": result["formatting_only"],
        "change_counts": result["summary"],
        "symbols": symbols,
        "symbols_truncated": len(result["changes"]) > _MAX_SYMBOLS,
        "behavior_equivalence_proven": False,
    }
    if cache is not None:
        cache.set(key, summary)
    return summary


def _valid(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "status", "method", "structural_equal", "formatting_only", "change_counts",
        "symbols", "symbols_truncated", "behavior_equivalence_proven",
    }:
        return False
    counts, symbols = value["change_counts"], value["symbols"]
    return (
        value["status"] == "observed" and value["method"] == "python_ast_v1"
        and value["behavior_equivalence_proven"] is False
        and all(type(value[k]) is bool for k in ("structural_equal", "formatting_only", "symbols_truncated"))
        and isinstance(counts, dict)
        and all(k in _KINDS and type(v) is int and 0 <= v <= 2001 for k, v in counts.items())
        and isinstance(symbols, list) and len(symbols) <= _MAX_SYMBOLS
        and all(
            isinstance(s, dict) and set(s) == {"symbol", "types"}
            and isinstance(s["symbol"], str) and len(s["symbol"]) <= 200
            and isinstance(s["types"], list) and all(isinstance(t, str) and t in _KINDS for t in s["types"])
            for s in symbols
        )
    )
