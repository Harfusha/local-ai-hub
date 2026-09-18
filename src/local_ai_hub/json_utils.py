from __future__ import annotations

import json
from typing import Any

try:
    import orjson as _orjson
except ImportError:  # pragma: no cover - depends on optional performance extra
    _orjson = None

try:
    import msgspec as _msgspec
except ImportError:  # pragma: no cover - depends on optional performance extra
    _msgspec = None


def backend_name() -> str:
    """Return active JSON backend without making optional packages mandatory."""
    if _orjson is not None:
        return "orjson"
    if _msgspec is not None:
        return "msgspec"
    return "stdlib"


def loads(value: str | bytes | bytearray) -> Any:
    """Decode JSON through an optional fast backend, preserving stdlib fallback."""
    if _orjson is not None:
        return _orjson.loads(value)
    if _msgspec is not None:
        return _msgspec.json.decode(value)
    return json.loads(value)


def dumps(value: Any, **kwargs: Any) -> str:
    """Serialize JSON compactly while preserving caller-specific options."""
    kwargs.setdefault("ensure_ascii", False)
    kwargs.setdefault("separators", (",", ":"))

    # Fast backends intentionally handle only the common compact path. The stdlib
    # remains authoritative for pretty output, custom separators, and uncommon
    # keyword combinations where backend semantics differ.
    supported = {"ensure_ascii", "separators", "sort_keys", "default"}
    compact = kwargs.get("separators") == (",", ":") and not kwargs.get("ensure_ascii", False)
    if compact and not (set(kwargs) - supported):
        if _orjson is not None:
            options = _orjson.OPT_SORT_KEYS if kwargs.get("sort_keys") else 0
            default = kwargs.get("default")
            if default is None:
                encoded = _orjson.dumps(value, option=options)
            else:
                encoded = _orjson.dumps(value, option=options, default=default)
            return encoded.decode("utf-8")
        if _msgspec is not None and not kwargs.get("sort_keys") and kwargs.get("default") is None:
            return _msgspec.json.encode(value).decode("utf-8")
    return json.dumps(value, **kwargs)
