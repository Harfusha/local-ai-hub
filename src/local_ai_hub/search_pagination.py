"""Shared hard bounds for public repository search pagination."""

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
