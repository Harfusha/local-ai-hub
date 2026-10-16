"""Shared hard bounds and utilities for public repository search pagination."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
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
    """Clamp integer pagination inputs while preserving a valid positive page."""
    if isinstance(default_limit, bool) or not isinstance(default_limit, int):
        raise TypeError("default_limit must be an integer")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)):
        raise TypeError("limit must be an integer")
    if offset is not None and (isinstance(offset, bool) or not isinstance(offset, int)):
        raise TypeError("offset must be an integer")

    def_lim = max(1, min(default_limit, MAX_PAGE_SIZE))
    clean_lim = def_lim if limit is None else max(1, min(limit, MAX_PAGE_SIZE))
    clean_off = 0 if offset is None else max(0, min(offset, MAX_PAGE_WINDOW - 1))
    clean_lim = min(clean_lim, MAX_PAGE_WINDOW - clean_off)

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
    items: Sequence[T] | None,
    limit: object = None,
    offset: object = None,
    default_limit: int = 20,
) -> tuple[list[T], int, bool]:
    """Slice items safely with clamped pagination, returning (items, total_count, has_more)."""
    lim, off = clamp_pagination(limit, offset, default_limit=default_limit)
    if items is None:
        return [], 0, False
    total_count = len(items)
    paged = list(items[off : off + lim])
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

    lim = default_limit if raw_lim is None else raw_lim
    off = 0 if raw_off is None else raw_off

    err = pagination_bounds_error(lim, off)
    if err is not None:
        if isinstance(lim, int) and not isinstance(lim, bool) and isinstance(off, int) and not isinstance(off, bool):
            clamped_lim, clamped_off = clamp_pagination(lim, off, default_limit=default_limit)
        else:
            clamped_lim, clamped_off = clamp_pagination(None, None, default_limit=default_limit)
        return clamped_lim, clamped_off, err

    return int(lim), int(off), None
