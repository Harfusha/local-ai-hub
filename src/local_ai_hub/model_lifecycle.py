from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
import gc
import math
import threading
import time
from typing import Any, Callable
import weakref


_CUDA_MODEL_LOCK = threading.RLock()
_CUDA_MODELS: weakref.WeakSet[Any] = weakref.WeakSet()
_MAX_LOCK_TIMEOUT_SECONDS = 86_400.0


def _safe_timeout(timeout_seconds: Any) -> float:
    if timeout_seconds is None or isinstance(timeout_seconds, bool):
        return 0.0
    try:
        parsed = float(timeout_seconds)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if math.isnan(parsed) or parsed < 0.0:
        return 0.0
    if math.isinf(parsed):
        return _MAX_LOCK_TIMEOUT_SECONDS
    return min(parsed, _MAX_LOCK_TIMEOUT_SECONDS)


@contextmanager
def acquire_locks(locks: Iterable[Any] | None, timeout_seconds: float):
    safe_timeout = _safe_timeout(timeout_seconds)
    deadline = time.monotonic() + safe_timeout
    acquired: list[Any] = []
    try:
        for lock in locks or ():
            remaining = min(_MAX_LOCK_TIMEOUT_SECONDS, max(0.0, deadline - time.monotonic()))
            if not lock.acquire(timeout=remaining):
                yield False
                return
            acquired.append(lock)
        yield True
    finally:
        for lock in reversed(acquired):
            lock.release()


def uses_torch_cuda(backend: str | None, device: str | None) -> bool:
    if isinstance(backend, bool) or isinstance(device, bool):
        return False
    normalized_backend = str(backend or "").replace("\x00", "").strip().lower()
    normalized_device = str(device or "").replace("\x00", "").strip().lower()
    return normalized_backend in {"torch", "sentence-transformers"} and normalized_device.startswith("cuda")


def active_cuda_model_count() -> int:
    with _CUDA_MODEL_LOCK:
        return len(_CUDA_MODELS)


def is_cuda_model_registered(owner: Any) -> bool:
    if owner is None:
        return False
    with _CUDA_MODEL_LOCK:
        try:
            return owner in _CUDA_MODELS
        except TypeError:
            return False


def load_model(owner: Any, *, uses_cuda: bool, factory: Callable[[], Any]) -> Any:
    if not uses_cuda:
        return factory()
    with _CUDA_MODEL_LOCK:
        model = factory()
        try:
            _CUDA_MODELS.add(owner)
        except TypeError:
            pass
        return model


def release_model(owner: Any, *, used_cuda: bool) -> bool:
    if not used_cuda:
        return False
    with _CUDA_MODEL_LOCK:
        try:
            if owner not in _CUDA_MODELS:
                return False
            _CUDA_MODELS.discard(owner)
        except TypeError:
            return False
        if _CUDA_MODELS:
            return False
        gc.collect()
        try:
            import torch

            cuda = getattr(torch, "cuda", None)
            synchronize = getattr(cuda, "synchronize", None)
            empty_cache = getattr(cuda, "empty_cache", None)
            if callable(synchronize):
                synchronize()
            if callable(empty_cache):
                empty_cache()
                return True
        except Exception:
            pass
        return False
