"""Bounded structural summaries of exact Git blobs, without source retention."""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from .ast_diff import ast_diff

_INDEX = re.compile(rb"^index ([0-9a-f]{40,64})\.\.([0-9a-f]{40,64})(?: [0-7]{6})?$", re.MULTILINE)
_MAX_SOURCE = 256 * 1024
_MAX_SYMBOLS = 24
_KINDS = {"added", "removed", "modified", "renamed", "moved", "reordered", "module_modified"}


def summarize_python_patch(
    patch: bytes, git: Callable[..., bytes], *, cache: Any | None = None, key: str,
) -> dict[str, Any]:
    """Summarize only full object identities that Git can actually resolve.

    An unstaged worktree blob usually does not exist in the object database.
    Reconstructing it from a validated patch is separate work; never substitute
    an arbitrary live filesystem read or mutate Git by writing the blob.
    """
    match = _INDEX.search(patch)
    if match is None:
        return {"status": "unavailable", "reason": "no_blob_pair"}
    if cache is not None:
        stored = cache.get(key)
        if _valid(stored):
            return stored
    sources = []
    for raw in match.groups():
        oid = raw.decode("ascii")
        if not oid.strip("0"):
            sources.append("")
            continue
        try:
            if git("cat-file", "-t", oid).strip() != b"blob":
                return {"status": "unavailable", "reason": "not_blob"}
            size = int(git("cat-file", "-s", oid).strip())
            if not 0 <= size <= _MAX_SOURCE:
                return {"status": "unavailable", "reason": "source_budget"}
            content = git("cat-file", "blob", oid)
            if len(content) != size:
                return {"status": "unavailable", "reason": "blob_size_mismatch"}
            sources.append(content.decode("utf-8"))
        except (ValueError, UnicodeError):
            return {"status": "unavailable", "reason": "blob_unavailable"}
    result = ast_diff(*sources)
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
