from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def _bounded(value: Any, limit: int) -> str:
    if value is None or isinstance(value, bool) or limit <= 0:
        return ""
    return str(value).replace("\x00", "").strip()[:limit]


def _ids(values: Iterable[Any] | None) -> list[str]:
    if values is None or isinstance(values, bool):
        return []
    if isinstance(values, (str, bytes)):
        raw_items: Iterable[Any] = (values,)
    elif isinstance(values, Mapping):
        raw_items = ()
    else:
        try:
            raw_items = list(values)
        except TypeError:
            raw_items = (values,)
    result: list[str] = []
    seen: set[str] = set()
    for value in raw_items:
        item = _bounded(value, 120)
        if item and item not in seen:
            result.append(item)
            seen.add(item)
        if len(result) >= 64:
            break
    return result


def is_stale_evidence_meta(meta: Mapping[str, Any] | object) -> bool:
    if not isinstance(meta, Mapping):
        return False
    return bool(meta.get("stale")) or str(meta.get("status") or "").strip().lower() == "stale"


def has_evidence_ids(meta: Mapping[str, Any] | object) -> bool:
    if not isinstance(meta, Mapping):
        return False
    ids = meta.get("evidence_ids")
    return isinstance(ids, (list, tuple)) and len(ids) > 0


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
