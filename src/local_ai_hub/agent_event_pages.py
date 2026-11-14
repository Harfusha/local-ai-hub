from __future__ import annotations

from typing import Any, Callable

from .json_utils import dumps as json_dumps, dumps_bytes as json_dumps_bytes

# Any marks decoded JSON values passed to the serializer and injected test seams.
AGENT_EVENT_PAGE_MAX_BYTES = 1024 * 1024
AGENT_EVENT_PAGE_MAX_LIMIT = 100


def _json_bytes(data: Any) -> bytes:
    return json_dumps_bytes(data)


def _minimum_json_bytes(value: Any, ceiling: int) -> int:
    """Lower bound UTF-8 JSON size without encoding potentially huge event values."""
    if isinstance(value, str):
        return min(len(value) + 2, ceiling + 1)
    if value is None:
        return 4
    if value is True:
        return 4
    if value is False:
        return 5
    if isinstance(value, (int, float)):
        try:
            return min(len(json_dumps(value).encode("ascii")), ceiling + 1)
        except (OverflowError, ValueError):
            return ceiling + 1
    total = 0
    if isinstance(value, dict):
        total = 2 + max(0, len(value) - 1)
        if total > ceiling:
            return ceiling + 1
        for key, item in value.items():
            total += _minimum_json_bytes(key, ceiling - total)
            if total > ceiling:
                return ceiling + 1
            total += 1 + _minimum_json_bytes(item, ceiling - total)
            if total > ceiling:
                return ceiling + 1
    elif isinstance(value, (list, tuple)):
        total = 2 + max(0, len(value) - 1)
        if total > ceiling:
            return ceiling + 1
        for item in value:
            total += _minimum_json_bytes(item, ceiling - total)
            if total > ceiling:
                return ceiling + 1
    return total


def _bound_agent_event_page(
    status: int,
    page: dict[str, Any],
    after_seq: Any,
    *,
    json_bytes: Callable[[Any], bytes] = _json_bytes,
    minimum_json_bytes: Callable[[Any, int], int] = _minimum_json_bytes,
    max_bytes: int = AGENT_EVENT_PAGE_MAX_BYTES,
) -> tuple[int, dict[str, Any]]:
    """Bound serialized event pages while keeping the cursor on the last returned row."""
    try:
        cursor = max(0, int(after_seq))
    except (TypeError, ValueError, OverflowError):
        cursor = 0

    original_events = list(page.get("events") or [])
    if not original_events:
        return (status, page) if len(json_bytes(page)) <= max_bytes else (
            413,
            {
                "success": False, "events": [], "next_seq": cursor,
                "first_retained_seq": max(0, int(page.get("first_retained_seq") or 0)),
                "last_seq": max(0, int(page.get("last_seq") or 0)), "has_more": False,
                "gap_ranges": [], "cursor_reset": bool(page.get("cursor_reset")),
                "error": {"code": "agent_event_page_too_large", "message": "event page metadata exceeds serialized response byte limit", "max_bytes": max_bytes},
            },
        )

    event_bytes = 0
    best_page: dict[str, Any] | None = None
    for index, event in enumerate(original_events):
        candidate = dict(page)
        try:
            candidate["next_seq"] = max(0, int(event.get("seq") or 0))
        except (AttributeError, TypeError, ValueError, OverflowError):
            break
        trimmed = index + 1 < len(original_events)
        candidate["has_more"] = bool(page.get("has_more")) or trimmed
        candidate["gap_ranges"] = [
            gap for gap in (page.get("gap_ranges") or [])
            if isinstance(gap, dict) and int(gap.get("to_seq") or 0) <= candidate["next_seq"]
        ]
        candidate["events"] = []
        envelope_bytes = len(json_bytes(candidate)) - 2  # Replace serialized empty event list.
        separator_bytes = 1 if index else 0
        if envelope_bytes + event_bytes + separator_bytes + minimum_json_bytes(
            event, max_bytes
        ) > max_bytes:
            break
        item_bytes = len(json_bytes(event))
        if envelope_bytes + event_bytes + separator_bytes + item_bytes > max_bytes:
            break
        event_bytes += item_bytes
        candidate["events"] = original_events[:index + 1]
        best_page = candidate
    if best_page is not None:
        return status, best_page

    # A single event can exceed the budget through uncapped metadata fields.
    # Keep the caller cursor unchanged so retry cannot silently skip that row.
    return 413, {
        "success": False,
        "events": [],
        "next_seq": cursor,
        "first_retained_seq": max(0, int(page.get("first_retained_seq") or 0)),
        "last_seq": max(0, int(page.get("last_seq") or 0)),
        "has_more": bool(page.get("has_more")) or bool(original_events),
        "gap_ranges": [],
        "cursor_reset": bool(page.get("cursor_reset")),
        "error": {
            "code": "agent_event_page_too_large",
            "message": "first event exceeds serialized response byte limit",
            "max_bytes": max_bytes,
        },
    }
