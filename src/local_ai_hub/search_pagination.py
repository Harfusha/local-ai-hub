"""Shared hard bounds and utilities for public repository search pagination."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, TypeVar

T = TypeVar("T")

MAX_PAGE_SIZE = 200
MAX_PAGE_WINDOW = 2048
MAX_HTTP_PAGE_RESPONSE_BYTES = 4 * 1024 * 1024


def pagination_bounds_error(limit: object, offset: object) -> str | None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_PAGE_SIZE:
        return f"limit must be an integer from 1 to {MAX_PAGE_SIZE}"
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        return "offset must be a non-negative integer"
    if offset + limit > MAX_PAGE_WINDOW:
        return f"offset + limit must not exceed {MAX_PAGE_WINDOW}"
    return None


def is_valid_pagination(limit: object, offset: object) -> bool:
    """Return True if limit and offset satisfy pagination bounds."""
    return pagination_bounds_error(limit, offset) is None


def clamp_pagination(
    limit: object = None,
    offset: object = None,
    default_limit: int = 20,
) -> tuple[int, int]:
    """Safely clamp any limit and offset inputs to valid pagination bounds."""
    try:
        def_lim = int(default_limit)
        def_lim = max(1, min(def_lim, MAX_PAGE_SIZE))
    except (TypeError, ValueError):
        def_lim = 20

    try:
        if limit is None or isinstance(limit, bool):
            clean_lim = def_lim
        else:
            clean_lim = int(limit)
    except (TypeError, ValueError, OverflowError):
        clean_lim = def_lim

    try:
        if offset is None or isinstance(offset, bool):
            clean_off = 0
        else:
            clean_off = int(offset)
    except (TypeError, ValueError, OverflowError):
        clean_off = 0

    clean_off = max(0, min(clean_off, MAX_PAGE_WINDOW))
    clean_lim = max(1, min(clean_lim, MAX_PAGE_SIZE))

    if clean_off + clean_lim > MAX_PAGE_WINDOW:
        clean_lim = max(0, MAX_PAGE_WINDOW - clean_off)

    return clean_lim, clean_off


def pagination_slice(
    limit: object = None,
    offset: object = None,
    default_limit: int = 20,
) -> slice:
    """Return a slice for the clamped pagination range."""
    lim, off = clamp_pagination(limit, offset, default_limit=default_limit)
    return slice(off, off + lim)


def paginate_sequence(
    items: Sequence[T] | Iterable[T] | None,
    limit: object = None,
    offset: object = None,
    default_limit: int = 20,
) -> tuple[list[T], int, bool]:
    """Slice items safely with clamped pagination, returning (items, total_count, has_more)."""
    if items is None:
        return [], 0, False
    if not isinstance(items, Sequence):
        if isinstance(items, Iterable) and not isinstance(items, (str, bytes)):
            try:
                seq = list(items)
            except Exception:
                return [], 0, False
        else:
            return [], 0, False
    else:
        seq = items
    total_count = len(seq)
    lim, off = clamp_pagination(limit, offset, default_limit=default_limit)
    paged = list(seq[off : off + lim])
    has_more = (off + len(paged)) < total_count
    return paged, total_count, has_more


def parse_pagination_mapping(
    params: Mapping[str, Any] | None,
    limit_key: str = "limit",
    offset_key: str = "offset",
    default_limit: int = 20,
) -> tuple[int, int, str | None]:
    """Extract and validate pagination from a mapping (e.g. MCP args or query dict)."""
    if params is None or not isinstance(params, Mapping):
        lim, off = clamp_pagination(None, None, default_limit=default_limit)
        return lim, off, None

    raw_lim = params.get(limit_key)
    raw_off = params.get(offset_key)

    if raw_lim is None and raw_off is None:
        lim, off = clamp_pagination(None, None, default_limit=default_limit)
        return lim, off, None

    try:
        lim = int(raw_lim) if raw_lim is not None and not isinstance(raw_lim, bool) else (default_limit if raw_lim is None else raw_lim)
    except (TypeError, ValueError, OverflowError):
        lim = raw_lim

    try:
        off = int(raw_off) if raw_off is not None and not isinstance(raw_off, bool) else (0 if raw_off is None else raw_off)
    except (TypeError, ValueError, OverflowError):
        off = raw_off

    err = pagination_bounds_error(lim, off)
    if err is not None:
        clamped_lim, clamped_off = clamp_pagination(raw_lim, raw_off, default_limit=default_limit)
        return clamped_lim, clamped_off, err

    return int(lim), int(off), None
