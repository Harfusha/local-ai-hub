"""Pure flattening of nested configuration values."""

from __future__ import annotations

from typing import Any


def flatten_config_values(
    value: Any,
    prefix: str = "",
    out: list[str] | None = None,
    limit: int = 200,
) -> list[str]:
    """Return bounded dotted paths for nested dictionaries and lists."""
    out = out if out is not None else []
    if len(out) >= limit:
        return out
    if isinstance(value, dict):
        for key, child in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            out.append(name)
            flatten_config_values(child, name, out, limit)
            if len(out) >= limit: break
    elif isinstance(value, list):
        for child in value[:8]:
            flatten_config_values(child, prefix, out, limit)
            if len(out) >= limit: break
    return out
