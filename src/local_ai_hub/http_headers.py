"""HTTP CORS and response header helpers."""
from __future__ import annotations

from typing import Any


def apply_cors_headers(
    send_header_fn: Any,
    origin: str | None = None,
    methods: str = "GET, POST, OPTIONS",
) -> None:
    """Apply standard CORS response headers via the provided send_header callable.

    Args:
        send_header_fn: Callable or handler instance providing a send_header method.
        origin: The request Origin header value, if present.
        methods: Allowed HTTP methods (defaults to "GET, POST, OPTIONS").
    """
    if not origin:
        return
    resolved_origin = str(origin).strip()
    if not resolved_origin:
        return
    header_fn = getattr(send_header_fn, "send_header", send_header_fn)
    header_fn("Access-Control-Allow-Origin", resolved_origin)
    header_fn("Access-Control-Allow-Methods", methods)
    header_fn("Access-Control-Allow-Headers", "Content-Type")
    header_fn("Vary", "Origin")


def standard_json_headers(content_length: int) -> list[tuple[str, str]]:
    """Return standard HTTP headers for a JSON response payload.

    Args:
        content_length: Length of the response body in bytes.

    Returns:
        List of (header_name, header_value) pairs.
    """
    return [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(content_length)),
    ]
