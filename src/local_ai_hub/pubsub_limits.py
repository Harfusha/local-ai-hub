"""Bounded JSON snapshots for process-local pubsub retention and fanout."""
from __future__ import annotations

import json
from typing import Any


def snapshot_message(value: Any, max_bytes: int) -> tuple[Any, int]:
    """Copy JSON data without first serializing an unbounded caller graph."""
    nodes, size = 0, 0
    ancestors: set[int] = set()

    def charge(amount: int) -> None:
        nonlocal size
        size += amount
        if size > max_bytes:
            raise ValueError("pubsub message byte limit exceeded")

    def scalar(item: Any) -> Any:
        if isinstance(item, str) and len(item) > max_bytes:
            raise ValueError("pubsub message byte limit exceeded")
        if isinstance(item, int) and item.bit_length() > 4096:
            raise ValueError("pubsub integer exceeds supported size")
        charge(len(json.dumps(item, ensure_ascii=False, allow_nan=False).encode("utf-8")))
        return item

    def copy(item: Any, depth: int) -> Any:
        nonlocal nodes
        nodes += 1
        if nodes > 4096 or depth > 32:
            raise ValueError("pubsub message structure limit exceeded")
        if item is None or isinstance(item, (str, bool, int, float)):
            return scalar(item)
        if not isinstance(item, (dict, list, tuple)):
            raise ValueError("pubsub message must contain JSON values only")
        if len(item) > 4096 or id(item) in ancestors:
            raise ValueError("pubsub message is cyclic or exceeds structure limits")
        ancestors.add(id(item))
        try:
            charge(2 + max(0, len(item) - 1))
            if isinstance(item, dict):
                result: dict[str, Any] = {}
                for key, child in item.items():
                    if not isinstance(key, str):
                        raise ValueError("pubsub message keys must be strings")
                    nodes += 1
                    if nodes > 4096:
                        raise ValueError("pubsub message structure limit exceeded")
                    scalar(key)
                    charge(1)
                    result[key] = copy(child, depth + 1)
                return result
            return [copy(child, depth + 1) for child in item]
        finally:
            ancestors.remove(id(item))

    result = copy(value, 0)
    return result, size


def bounded_name(value: str, name: str, *, allow_empty: bool = False, strip: bool = True) -> str:
    if not isinstance(value, str) or len(value) > 512 or "\x00" in value:
        raise ValueError(f"pubsub {name} must be a string of at most 512 characters")
    if not value.strip() and not allow_empty:
        raise ValueError(f"pubsub {name} must not be empty")
    return value.strip() if strip else value
