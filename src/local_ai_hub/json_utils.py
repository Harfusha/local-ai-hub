from __future__ import annotations

import json
import math
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


def loads(value: str | bytes | bytearray | memoryview) -> Any:
    """Decode JSON through an optional fast backend, preserving stdlib fallback."""
    if isinstance(value, str):
        if value.startswith("\ufeff"):
            value = value[1:]
    elif isinstance(value, (bytes, bytearray, memoryview)):
        if bytes(value[:3]) == b"\xef\xbb\xbf":
            value = value[3:]

    if _orjson is not None:
        return _orjson.loads(value)
    if _msgspec is not None:
        return _msgspec.json.decode(value)
    if isinstance(value, memoryview):
        value = bytes(value)
    return json.loads(value)


def safe_loads(value: Any, default: Any = None) -> Any:
    """Decode JSON or return default when input is not valid JSON text/bytes."""
    if not isinstance(value, (str, bytes, bytearray, memoryview)):
        return default
    try:
        return loads(value)
    except Exception:
        return default


def _validate_sanitize_options(safe_floats: Any, handle_cycles: Any, max_depth: Any) -> None:
    if not isinstance(safe_floats, bool) or not isinstance(handle_cycles, bool):
        raise TypeError("safe_floats and handle_cycles must be booleans")
    if isinstance(max_depth, bool) or not isinstance(max_depth, int) or not 0 <= max_depth <= 128:
        raise ValueError("max_depth must be an integer from 0 to 128")


def sanitize_value(
    value: Any,
    *,
    safe_floats: bool = True,
    handle_cycles: bool = True,
    max_depth: int = 128,
    cycle_sentinel: str = "[Circular]",
    max_depth_sentinel: str = "[MaxDepthExceeded]",
) -> Any:
    """Sanitize data structure by converting non-finite floats to None, breaking cycles, and bounding depth."""
    _validate_sanitize_options(safe_floats, handle_cycles, max_depth)
    seen: set[int] = set()

    def _walk(curr: Any, depth: int) -> Any:
        if depth >= max_depth:
            return max_depth_sentinel

        if safe_floats and isinstance(curr, float) and (math.isnan(curr) or math.isinf(curr)):
            return None

        if isinstance(curr, dict):
            ident = id(curr)
            if handle_cycles and ident in seen:
                return cycle_sentinel
            if handle_cycles:
                seen.add(ident)
            try:
                return {k: _walk(v, depth + 1) for k, v in curr.items()}
            finally:
                if handle_cycles:
                    seen.remove(ident)

        if isinstance(curr, (list, tuple)):
            ident = id(curr)
            if handle_cycles and ident in seen:
                return cycle_sentinel
            if handle_cycles:
                seen.add(ident)
            try:
                res = [_walk(item, depth + 1) for item in curr]
                return tuple(res) if isinstance(curr, tuple) else res
            finally:
                if handle_cycles:
                    seen.remove(ident)

        return curr

    return _walk(value, 0)


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
    safe_floats = kwargs.pop("safe_floats", False)
    handle_cycles = kwargs.pop("handle_cycles", False)
    max_depth = kwargs.pop("max_depth", None)
    _validate_sanitize_options(safe_floats, handle_cycles, 128 if max_depth is None else max_depth)

    if safe_floats or handle_cycles or max_depth is not None:
        opts: dict[str, Any] = {"safe_floats": safe_floats, "handle_cycles": handle_cycles}
        if max_depth is not None:
            opts["max_depth"] = max_depth
        value = sanitize_value(value, **opts)

    kwargs.setdefault("ensure_ascii", False)
    kwargs.setdefault("separators", (",", ":"))

    # Fast backends intentionally handle only the common compact path. The stdlib
    # remains authoritative for pretty output, custom separators, and uncommon
    # keyword combinations where backend semantics differ.
    supported = {"ensure_ascii", "separators", "sort_keys", "default", "allow_nan"}
    compact = kwargs.get("separators") == (",", ":") and not kwargs.get("ensure_ascii", False)
    if compact and not (set(kwargs) - supported):
        if kwargs.get("allow_nan") is False:
            return json.dumps(value, **kwargs)
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
    safe_floats = kwargs.pop("safe_floats", False)
    handle_cycles = kwargs.pop("handle_cycles", False)
    max_depth = kwargs.pop("max_depth", None)
    _validate_sanitize_options(safe_floats, handle_cycles, 128 if max_depth is None else max_depth)

    if safe_floats or handle_cycles or max_depth is not None:
        opts: dict[str, Any] = {"safe_floats": safe_floats, "handle_cycles": handle_cycles}
        if max_depth is not None:
            opts["max_depth"] = max_depth
        value = sanitize_value(value, **opts)

    kwargs.setdefault("ensure_ascii", False)
    kwargs.setdefault("separators", (",", ":"))

    supported = {"ensure_ascii", "separators", "sort_keys", "default", "allow_nan"}
    compact = kwargs.get("separators") == (",", ":") and not kwargs.get("ensure_ascii", False)
    if compact and not (set(kwargs) - supported):
        if kwargs.get("allow_nan") is False:
            return json.dumps(value, **kwargs).encode("utf-8")
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
