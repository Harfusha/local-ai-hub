from __future__ import annotations

import pytest

from local_ai_hub.search_pagination import (
    MAX_PAGE_SIZE,
    MAX_PAGE_WINDOW,
    clamp_pagination,
    is_valid_pagination,
    paginate_sequence,
    pagination_bounds_error,
    pagination_slice,
    parse_pagination_mapping,
)


def test_pagination_bounds_error_edge_cases() -> None:
    # Boolean values must be rejected
    assert pagination_bounds_error(True, 0) is not None
    assert pagination_bounds_error(10, False) is not None
    assert pagination_bounds_error(True, False) is not None

    # Limit boundaries
    assert pagination_bounds_error(0, 0) is not None
    assert pagination_bounds_error(MAX_PAGE_SIZE + 1, 0) is not None
    assert pagination_bounds_error(1, 0) is None
    assert pagination_bounds_error(MAX_PAGE_SIZE, 0) is None

    # Offset boundaries
    assert pagination_bounds_error(10, -1) is not None
    assert pagination_bounds_error(10, 0) is None

    # Window overflow
    assert pagination_bounds_error(1, MAX_PAGE_WINDOW) is not None
    assert pagination_bounds_error(MAX_PAGE_WINDOW, 0) is not None  # limit > MAX_PAGE_SIZE
    assert pagination_bounds_error(48, 2000) is None  # 48 + 2000 == 2048 == MAX_PAGE_WINDOW
    assert pagination_bounds_error(49, 2000) is not None  # 2049 > 2048


def test_is_valid_pagination() -> None:
    assert is_valid_pagination(50, 0) is True
    assert is_valid_pagination(48, 2000) is True
    assert is_valid_pagination(0, 0) is False
    assert is_valid_pagination(50, -5) is False
    assert is_valid_pagination(True, 0) is False
    assert is_valid_pagination(None, None) is False


def test_clamp_pagination() -> None:
    # Defaults on None or invalid values
    assert clamp_pagination(None, None) == (20, 0)
    assert clamp_pagination("invalid", "invalid") == (20, 0)

    # String coercions
    assert clamp_pagination("50", "10") == (50, 10)

    # Overflows and negative offsets
    assert clamp_pagination(9999, -50) == (MAX_PAGE_SIZE, 0)

    # Clamping against MAX_PAGE_WINDOW
    assert clamp_pagination(100, 2000) == (48, 2000)  # 2000 + 48 == 2048
    assert clamp_pagination(50, 3000) == (0, MAX_PAGE_WINDOW)


def test_paginate_sequence_and_slice() -> None:
    items = list(range(100))

    # First page
    paged, total, has_more = paginate_sequence(items, limit=10, offset=0)
    assert paged == list(range(10))
    assert total == 100
    assert has_more is True

    # Last page
    paged, total, has_more = paginate_sequence(items, limit=20, offset=90)
    assert paged == list(range(90, 100))
    assert total == 100
    assert has_more is False

    # None input safety
    assert paginate_sequence(None) == ([], 0, False)

    # Slice helper
    sl = pagination_slice(limit=25, offset=10)
    assert sl == slice(10, 35)


def test_parse_pagination_mapping() -> None:
    # Valid mapping
    lim, off, err = parse_pagination_mapping({"limit": 50, "offset": 10})
    assert lim == 50
    assert off == 10
    assert err is None

    # Empty mapping uses defaults
    lim, off, err = parse_pagination_mapping({})
    assert lim == 20
    assert off == 0
    assert err is None

    # None mapping
    lim, off, err = parse_pagination_mapping(None)
    assert lim == 20
    assert off == 0
    assert err is None

    # Out of bounds mapping returns error
    lim, off, err = parse_pagination_mapping({"limit": 500, "offset": 0})
    assert err is not None
