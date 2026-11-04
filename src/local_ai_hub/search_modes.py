"""Bounded, deterministic candidate fusion for repository search modes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any

SEARCH_MODES = ("lexical", "rag", "hybrid")
RRF_K = 60


def canonical_search_mode(value: Any) -> str | None:
    """Return one canonical public mode, rejecting coercions and aliases."""
    if type(value) is not str or value not in SEARCH_MODES:
        return None
    return value


def prefers_lexical_precision(query: str) -> bool:
    """Recognize compact symbol-like queries where exact hits must lead."""
    if type(query) is not str:
        return False
    value = query.strip()
    if not value or len(value) > 256 or any(ch.isspace() for ch in value):
        return False
    return (
        any(ch in value for ch in ("_", "::", "/", "\\", ".", "+", "#", "$", ":"))
        or any(ch.islower() for ch in value) and any(ch.isupper() for ch in value)
    )


def _path_key(item: Mapping[str, Any]) -> tuple[str, str] | None:
    path = item.get("path")
    if type(path) is not str or not path.strip():
        return None
    raw = path.replace("\\", "/")
    parts = PurePosixPath(raw).parts
    if (
        not raw
        or raw.startswith("/")
        or ".." in parts
        or (parts and ":" in parts[0])
        or "\x00" in raw
    ):
        return None
    display = str(PurePosixPath(raw))
    return display.casefold(), display


def fuse_search_results(
    lexical: Sequence[Mapping[str, Any]],
    rag: Sequence[Mapping[str, Any]],
    *,
    limit: int,
    offset: int,
    rrf_k: int = RRF_K,
    lexical_first: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fuse file-level lexical and RAG ranks without counting files twice.

    Each backend contributes at most once per file. The lexical snippet is kept
    when both backends agree, so semantic metadata cannot replace exact source.
    Counts describe only this bounded candidate pool; hybrid does not claim an
    exact total over the mixed result set.
    """
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    if type(rrf_k) is not int or rrf_k < 1:
        raise ValueError("rrf_k must be a positive integer")

    merged: dict[str, dict[str, Any]] = {}
    for source, rows in (("lexical", lexical), ("rag", rag)):
        seen: set[str] = set()
        for rank, raw in enumerate(rows, start=1):
            if not isinstance(raw, Mapping):
                continue
            identity = _path_key(raw)
            if identity is None:
                continue
            key, display_path = identity
            if key in seen:
                continue
            seen.add(key)
            entry = merged.get(key)
            if entry is None:
                entry = {
                    "path": display_path,
                    "sources": [],
                    "fusion_score": 0.0,
                }
                merged[key] = entry
            if source == "lexical":
                # Exact lexical coordinates and snippets remain authoritative.
                lexical_item = dict(raw)
                lexical_item.pop("sources", None)
                lexical_item.pop("fusion_score", None)
                entry.update(lexical_item)
                entry["path"] = display_path
            elif not entry.get("lexical_rank"):
                # RAG text is a candidate only; caller validates it against the
                # current source and path policy before fusion.
                for field, value in raw.items():
                    if field not in entry and field not in {"embedding", "raw_embedding"}:
                        entry[field] = value
            entry[f"{source}_rank"] = rank
            entry["fusion_score"] += 1.0 / (rrf_k + rank)
            entry["sources"].append(source)

    ranked = sorted(
        merged.values(),
        key=lambda item: (
            0 if lexical_first and item.get("lexical_rank") else 1,
            -float(item["fusion_score"]),
            str(item.get("path", "")).casefold(),
            str(item.get("path", "")),
        ),
    )
    for item in ranked:
        item["fusion_score"] = round(float(item["fusion_score"]), 8)
        item["sources"] = [source for source in ("lexical", "rag") if source in item["sources"]]
        item["result_source"] = "hybrid"
        item["score"] = item["fusion_score"]
    page = ranked[offset : offset + limit]
    metadata = {
        "candidate_count": len(ranked),
        "candidate_count_exact": False,
        "count_exact": False,
        "total_matches": None,
        "offset": offset,
        "limit": limit,
        "has_more": True if offset + len(page) < len(ranked) else None,
        "next_offset": offset + len(page),
    }
    return page, metadata
