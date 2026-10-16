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


def is_fast_backend() -> bool:
    """Return True when an optional fast JSON backend is active."""
    return backend_name() != "stdlib"


def loads(value: str | bytes | bytearray) -> Any:
    """Decode JSON through an optional fast backend, preserving stdlib fallback."""
    if _orjson is not None:
        return _orjson.loads(value)
    if _msgspec is not None:
        return _msgspec.json.decode(value)
    return json.loads(value)


def safe_loads(value: Any, default: Any = None) -> Any:
    """Decode JSON or return default when input is not valid JSON text/bytes."""
    if not isinstance(value, (str, bytes, bytearray)):
        return default
    try:
        return loads(value)
    except Exception:
        return default


def _has_non_string_mapping_key(value: Any) -> bool:
    pending = [value]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            identity = id(current)
            if identity in seen:
                continue
            seen.add(identity)
            for key, item in current.items():
                if not isinstance(key, str):
                    return True
                pending.append(item)
        elif isinstance(current, (list, tuple)):
            identity = id(current)
            if identity in seen:
                continue
            seen.add(identity)
            pending.extend(current)
    return False


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
        # A custom default may produce mapping keys not visible to the graph walk.
        if kwargs.get("sort_keys") and kwargs.get("default") is not None:
            return json.dumps(value, **kwargs)
        # orjson sorts coerced key strings, while the stdlib sorts original
        # key types before coercion. Keep canonical ordering for non-string keys.
        if kwargs.get("sort_keys") and _has_non_string_mapping_key(value):
            return json.dumps(value, **kwargs)
        if _orjson is not None:
            options = _orjson.OPT_NON_STR_KEYS
            if kwargs.get("sort_keys"):
                options |= _orjson.OPT_SORT_KEYS
            default = kwargs.get("default")
            if default is None:
                encoded = _orjson.dumps(value, option=options)
            else:
                encoded = _orjson.dumps(value, option=options, default=default)
            return encoded.decode("utf-8")
        if _msgspec is not None and not kwargs.get("sort_keys") and kwargs.get("default") is None:
            return _msgspec.json.encode(value).decode("utf-8")
    return json.dumps(value, **kwargs)


def dumps_bytes(value: Any, **kwargs: Any) -> bytes:
    """Serialize compact JSON directly to UTF-8 bytes when a fast backend exists."""
    kwargs.setdefault("ensure_ascii", False)
    kwargs.setdefault("separators", (",", ":"))

    supported = {"ensure_ascii", "separators", "sort_keys", "default"}
    compact = kwargs.get("separators") == (",", ":") and not kwargs.get("ensure_ascii", False)
    if compact and not (set(kwargs) - supported):
        if kwargs.get("sort_keys") and kwargs.get("default") is not None:
            return json.dumps(value, **kwargs).encode("utf-8", errors="replace")
        if kwargs.get("sort_keys") and _has_non_string_mapping_key(value):
            return json.dumps(value, **kwargs).encode("utf-8", errors="replace")
        if _orjson is not None:
            options = _orjson.OPT_NON_STR_KEYS
            if kwargs.get("sort_keys"):
                options |= _orjson.OPT_SORT_KEYS
            default = kwargs.get("default")
            if default is None:
                return _orjson.dumps(value, option=options)
            return _orjson.dumps(value, option=options, default=default)
        if _msgspec is not None and not kwargs.get("sort_keys") and kwargs.get("default") is None:
            return _msgspec.json.encode(value)
    return json.dumps(value, **kwargs).encode("utf-8", errors="replace")
