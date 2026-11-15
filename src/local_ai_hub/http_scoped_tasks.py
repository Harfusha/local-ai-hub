"""Bounded repository-scoped task paging over the existing task projection API.

The global task store paginates before HTTP root filtering. Filtering that
single global page made valid repository tasks disappear. Scan bounded global
pages and count *matching* rows for the requested pagination offset.
"""
from __future__ import annotations

from typing import Any, Callable


def page_scoped_tasks(
    list_tasks: Callable[..., Any],
    matches: Callable[[Any], bool],
    *,
    status: Any,
    limit: int,
    offset: int,
    include_stale: bool,
    query: str,
    max_scan: int = 10000,
    chunk_size: int = 200,
) -> dict[str, Any]:
    found: list[Any] = []
    scanned = 0
    matching_count = 0
    reached_end = False
    query_truncated = False

    while scanned < max_scan and len(found) <= limit:
        batch_limit = min(chunk_size, max_scan - scanned)
        batch = list_tasks(
            status=status, limit=batch_limit, offset=scanned,
            include_stale=include_stale, query=query,
        )
        query_truncated = query_truncated or bool(getattr(batch, "query_truncated", False))
        rows = list(batch)
        if not rows:
            reached_end = not query_truncated
            break
        for task in rows:
            if matches(task):
                if matching_count >= offset:
                    found.append(task)
                matching_count += 1
                if len(found) > limit:
                    break
        scanned += len(rows)
        if len(found) > limit:
            break
        if len(rows) < batch_limit:
            reached_end = not query_truncated
            break
        if query_truncated:
            break

    incomplete = query_truncated or not reached_end and len(found) <= limit
    result = found[:limit]
    return {
        "tasks": result,
        "next_offset": offset + len(result),
        "has_more": len(found) > limit or incomplete,
        "incomplete": incomplete,
        "total_count": matching_count if reached_end and offset == 0 else None,
        "global_rows_examined": scanned,
    }
