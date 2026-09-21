from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _bounded(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _ids(values: Iterable[Any] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        item = _bounded(value, 120)
        if item and item not in seen:
            result.append(item)
            seen.add(item)
        if len(result) >= 64:
            break
    return result


def evidence_meta(
    source: str,
    repository_revision: str,
    evidence_ids: Iterable[Any] | None,
    stale: bool,
    status: str,
    payload: Any = None,
) -> dict[str, Any]:
    """Return decision-grade provenance without retaining payload content."""
    is_stale = bool(stale)
    normalized_status = _bounded(status, 40).lower() or "unknown"
    if is_stale and normalized_status == "success":
        normalized_status = "stale"
    return {
        "source": _bounded(source, 120),
        "repository_revision": _bounded(repository_revision, 200),
        "evidence_ids": _ids(evidence_ids),
        "stale": is_stale,
        "status": normalized_status,
    }
