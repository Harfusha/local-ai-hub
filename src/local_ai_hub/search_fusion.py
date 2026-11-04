"""Deterministic file-level fusion of independent search candidate lists."""

from __future__ import annotations

import os
from pathlib import PurePosixPath
from typing import Any


def fuse_search_candidates(
    lexical: list[dict[str, Any]], semantic: list[dict[str, Any]], *, limit: int = 100
) -> list[dict[str, Any]]:
    """Fuse independent ranks once per file and source using reciprocal ranks.

    Callers must separately authorize paths and verify freshness against the
    owning root. This function only rejects structurally unsafe path spellings.
    """
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer")
    combined: dict[str, dict[str, Any]] = {}
    for source, candidates in (("lexical", lexical), ("semantic", semantic)):
        seen: set[str] = set()
        rank = 0
        for candidate in candidates:
            raw = candidate.get("path") if isinstance(candidate, dict) else None
            if not isinstance(raw, str) or not raw or "\x00" in raw:
                continue
            path = raw.replace("\\", "/")
            parts = PurePosixPath(path).parts
            if path.startswith("/") or not parts or ".." in parts or ":" in parts[0]:
                continue
            path = str(PurePosixPath(path))
            key = os.path.normcase(path)
            if key in seen:
                continue
            seen.add(key)
            rank += 1
            item = combined.get(key)
            if item is None:
                item = {**candidate, "path": path, "sources": [], "fusion_score": 0.0}
                combined[key] = item
            item["sources"].append(source)
            item["fusion_score"] += 1.0 / (60 + rank)
    ranked = sorted(
        combined.values(),
        key=lambda item: (-item["fusion_score"], "lexical" not in item["sources"], item["path"]),
    )
    return ranked[:limit]
