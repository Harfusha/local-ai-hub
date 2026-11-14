from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any


logger = logging.getLogger("local_ai_hub.deterministic")


def collect_exact_evidence(
    engine: Any, root: str, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if engine.evidence is None or engine.max_evidence <= 0:
        return []
    base = Path(root).resolve()
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    seen_ranges: set[tuple[str, int, int]] = set()
    snapshots: dict[str, tuple[str, list[str]] | None] = {}
    for row in rows:
        path = str(row.get("path", ""))
        if not path:
            continue
        line = max(1, int(row.get("line", 1) or 1))
        target = (base / path).resolve(strict=False)
        try:
            path = target.relative_to(base).as_posix()
        except ValueError:
            continue
        key = (path, line)
        if not path or key in seen:
            continue
        seen.add(key)
        if path not in snapshots:
            try:
                snapshots[path] = engine.repo_tools._read_snapshot(target)
            except OSError as read_exc:
                logger.debug("Exact evidence source skipped (%s)", type(read_exc).__name__)
                snapshots[path] = None
        snapshot = snapshots[path]
        if snapshot is None:
            continue
        digest, lines = snapshot
        if not lines or line > len(lines):
            continue
        start = max(1, line - 2)
        end = min(len(lines), line + 2)
        bounds = None
        bounds_reader = getattr(engine.code_index, "symbol_bounds_at", None)
        if callable(bounds_reader):
            try:
                bounds = bounds_reader(str(base), path, line, content_hash=digest)
            except (OSError, sqlite3.DatabaseError, TypeError, ValueError):
                bounds = None
        valid_bounds = (
            isinstance(bounds, tuple) and len(bounds) == 2
            and all(isinstance(value, int) and not isinstance(value, bool) for value in bounds)
        )
        if valid_bounds and 1 <= bounds[0] <= line <= bounds[1] <= len(lines):
            start, end = bounds
        else:
            bounds = None
        range_key = (path, start, end)
        if range_key in seen_ranges:
            continue
        seen_ranges.add(range_key)
        candidates.append({
            "path": path,
            "start_line": start,
            "end_line": end,
            "file_sha256": digest,
            "symbol_complete": bounds is not None,
        })
        if len(candidates) >= engine.max_evidence:
            break

    items: list[dict[str, Any]] = []
    merged_items = engine.merge_overlapping_slices(str(base), candidates)
    put_many = getattr(engine.evidence, "put_many", None)
    record_source = getattr(engine.evidence, "record_source_provenance", None)
    if callable(put_many):
        stored_items = put_many(str(base), merged_items)
        for item, stored in zip(merged_items, stored_items):
            if isinstance(stored, dict) and stored.get("evidence_id"):
                item["evidence_id"] = stored["evidence_id"]
                if callable(record_source):
                    record_source(str(item["evidence_id"]), root=str(base), source_code="indexed")
            item.pop("text", None)  # progressive disclosure at the API boundary
            items.append(item)
    else:
        for item in merged_items:
            eid = engine.evidence.put(str(base), item)
            if eid:
                item["evidence_id"] = eid
                if callable(record_source):
                    record_source(str(eid), root=str(base), source_code="indexed")
            item.pop("text", None)  # progressive disclosure at the API boundary
            items.append(item)
    return items
