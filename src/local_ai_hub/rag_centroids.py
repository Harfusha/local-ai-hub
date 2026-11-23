from __future__ import annotations

from collections import OrderedDict
import json
import threading
from typing import Any

from .rag_constants import (
    _CENTROID_CACHE_MAX_BYTES,
    _CENTROID_CACHE_MAX_ENTRIES,
    _CENTROID_ENTRY_MAX_BYTES,
    _CENTROID_FILTER_MIN_CHUNKS,
)

_CENTROID_CACHE_LOCK = threading.RLock()
_CENTROID_BUILD_LOCK = threading.Lock()
_CENTROID_CACHE: OrderedDict[tuple[Any, ...], tuple[Any, dict[int, tuple[tuple[str, int], ...]], int]] = OrderedDict()
_CENTROID_CACHE_BYTES = 0


def _centroid_threshold_reached(chunk_count: int) -> bool:
    return chunk_count > _CENTROID_FILTER_MIN_CHUNKS


def _fine_cosine_scores(matrix: Any, query_vector: Any) -> Any:
    """Exact cosine stage, kept separate so candidate filtering stays measurable."""
    import numpy as np

    norms = np.linalg.norm(matrix, axis=1)
    valid = np.isfinite(norms) & (norms > 1e-9)
    if valid.any():
        dot_scores = np.dot(matrix, query_vector)
        np.divide(dot_scores, norms, out=norms, where=valid)
    norms[~valid] = 0.0
    norms[~np.isfinite(norms)] = 0.0
    return norms


def _decode_centroid_vector(raw: Any, dimension: int, np: Any) -> Any | None:
    try:
        if isinstance(raw, (bytes, memoryview)):
            vector = np.frombuffer(raw, dtype=np.float32)
        elif isinstance(raw, str):
            vector = np.asarray(json.loads(raw), dtype=np.float32)
        else:
            return None
        vector = np.asarray(vector, dtype=np.float32).reshape(-1)
        if vector.size != dimension or not np.isfinite(vector).all():
            return None
        norm = float(np.linalg.norm(vector))
        if norm > 1e-9:
            vector = vector / norm
        return vector
    except Exception:
        return None


def _centroid_cache_get(key: tuple[Any, ...]) -> tuple[Any, dict[int, tuple[tuple[str, int], ...]], int] | None:
    with _CENTROID_CACHE_LOCK:
        value = _CENTROID_CACHE.get(key)
        if value is not None:
            _CENTROID_CACHE.move_to_end(key)
        return value


def _centroid_cache_put(
    key: tuple[Any, ...],
    value: tuple[Any, dict[int, tuple[tuple[str, int], ...]], int],
) -> bool:
    global _CENTROID_CACHE_BYTES
    size = value[2]
    if size > _CENTROID_ENTRY_MAX_BYTES:
        return False
    with _CENTROID_CACHE_LOCK:
        for old_key in tuple(_CENTROID_CACHE):
            if old_key != key and old_key[:4] == key[:4]:
                _CENTROID_CACHE_BYTES -= _CENTROID_CACHE.pop(old_key)[2]
        previous = _CENTROID_CACHE.pop(key, None)
        if previous is not None:
            _CENTROID_CACHE_BYTES -= previous[2]
        while _CENTROID_CACHE and (
            len(_CENTROID_CACHE) >= _CENTROID_CACHE_MAX_ENTRIES
            or _CENTROID_CACHE_BYTES + size > _CENTROID_CACHE_MAX_BYTES
        ):
            _, evicted = _CENTROID_CACHE.popitem(last=False)
            _CENTROID_CACHE_BYTES -= evicted[2]
        _CENTROID_CACHE[key] = value
        _CENTROID_CACHE_BYTES += size
    return True
