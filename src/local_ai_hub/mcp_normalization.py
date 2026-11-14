from __future__ import annotations

from typing import Any


# Any marks the dynamic JSON boundary; normalization preserves caller value shape.
def _normalize_deterministic(val: Any) -> Any:
    """Sort dictionary keys and normalize microsecond timestamps to maintain stable prompt caches."""
    if isinstance(val, dict):
        out = {}
        for key in sorted(val.keys()):
            out[key] = _normalize_deterministic(val[key])
        return out
    if isinstance(val, list):
        return [_normalize_deterministic(item) for item in val]
    return val
