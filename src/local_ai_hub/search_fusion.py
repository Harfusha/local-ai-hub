"""Deterministic file-level fusion that preserves chunk-level evidence."""

from __future__ import annotations

import math
from pathlib import PurePosixPath
from typing import Any


def _canonical_path(raw: Any, *, case_sensitive: bool) -> tuple[str, str] | None:
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        return None
    path = raw.replace("\\", "/")
    if path.startswith("/") or (path and ":" in path.split("/", 1)[0]):
        return None
    parts = [part for part in path.split("/") if part not in {"", "."}]
    if not parts or ".." in parts:
        return None
    canonical = PurePosixPath(*parts).as_posix()
    # Git paths are case-sensitive by default. Repositories that explicitly
    # use a case-insensitive identity policy can opt in without host OS drift.
    return canonical, canonical if case_sensitive else canonical.casefold()


def _match_key(match: dict[str, Any]) -> tuple[str, str, str] | None:
    source_id = match.get("source_id")
    chunk_id = match.get("chunk_id")
    content_hash = match.get("content_hash")
    if not isinstance(content_hash, str) or not content_hash:
        return None
    if isinstance(source_id, str) and source_id and isinstance(chunk_id, str) and chunk_id:
        return source_id, chunk_id, content_hash
    # Some current RAG rows use path and chunk_no as their stable identifiers.
    if isinstance(chunk_id, str) and chunk_id:
        return "", chunk_id, content_hash
    if type(match.get("chunk_no")) is int:
        return str(match.get("path", "")), str(match["chunk_no"]), content_hash
    return None


def fuse_search_candidates(
    lexical: list[dict[str, Any]],
    semantic: list[dict[str, Any]],
    *,
    limit: int = 100,
    matches_per_file: int = 8,
    case_sensitive: bool = True,
) -> list[dict[str, Any]]:
    """Fuse per-file ranks and retain bounded, typed chunk evidence.

    Paths are Git-relative, slash-normalized, and case-sensitive by default.
    No host filesystem policy participates in identity. Callers still authorize
    paths and verify freshness against the owning repository root.
    """
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer")
    if type(matches_per_file) is not int or matches_per_file < 1:
        raise ValueError("matches_per_file must be a positive integer")
    if type(case_sensitive) is not bool:
        raise ValueError("case_sensitive must be a boolean")

    combined: dict[str, dict[str, Any]] = {}
    for source, candidates in (("lexical", lexical), ("semantic", semantic)):
        seen_files: dict[str, int] = {}
        rank = 0
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            normalized = _canonical_path(candidate.get("path"), case_sensitive=case_sensitive)
            if normalized is None:
                continue
            path, key = normalized
            first_for_source = key not in seen_files
            if first_for_source:
                rank += 1
                seen_files[key] = rank
            source_rank = seen_files[key]
            file_score = 1.0 / (60 + source_rank)
            item = combined.get(key)
            if item is None:
                item = {
                    **candidate,
                    "path": path,
                    "sources": [],
                    "source_breakdown": {},
                    "fusion_score": 0.0,
                    "matches": [],
                }
                combined[key] = item
            if first_for_source:
                item["sources"].append(source)
                item["source_breakdown"][source] = {"rank": source_rank, "score": file_score}
                item["fusion_score"] += file_score

            match = {
                name: value for name, value in candidate.items()
                if name not in {"path", "sources", "source_breakdown", "fusion_score", "matches"}
            }
            match["path"] = path
            match["source"] = source
            match["source_rank"] = source_rank
            match["fusion_score"] = file_score
            identity = _match_key(match)
            existing = next((row for row in item["matches"] if identity is not None and row.get("_identity") == identity), None)
            if existing is None:
                match["_identity"] = identity
                match["sources"] = [source]
                item["matches"].append(match)
            elif source not in existing["sources"]:
                existing["sources"].append(source)
                existing["fusion_score"] = float(existing.get("fusion_score", 0.0)) + file_score

    ranked: list[dict[str, Any]] = []
    for item in combined.values():
        matches = sorted(
            item["matches"],
            key=lambda match: (
                not (type(match.get("relevance")) in {int, float} and math.isfinite(match["relevance"])),
                -float(match["relevance"])
                if type(match.get("relevance")) in {int, float} and math.isfinite(match["relevance"])
                else 0.0,
                -float(match.get("fusion_score", 0.0)),
                "lexical" not in match.get("sources", []),
                int(match.get("source_rank", 0)),
                str(match.get("chunk_id", match.get("chunk_no", ""))),
            ),
        )
        total_matches = len(matches)
        kept = matches[:matches_per_file]
        for match in kept:
            match.pop("_identity", None)
        item["matches"] = kept
        item["primary_match"] = kept[0] if kept else None
        item["alternative_matches"] = kept[1:]
        item["truncated"] = total_matches > len(kept)
        item["omitted_matches"] = total_matches - len(kept)
        item["sources"] = sorted(set(item["sources"]))
        ranked.append(item)

    ranked.sort(
        key=lambda item: (
            -item["fusion_score"],
            "lexical" not in item["sources"],
            item["path"],
        )
    )
    return ranked[:limit]
