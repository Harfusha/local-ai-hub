from __future__ import annotations

import gc
import threading
import time
import weakref
from contextlib import contextmanager
from typing import Any, Callable


_CUDA_MODEL_LOCK = threading.RLock()
_CUDA_MODELS: weakref.WeakSet[Any] = weakref.WeakSet()


@contextmanager
def acquire_locks(locks: tuple[Any, ...], timeout_seconds: float):
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    acquired: list[Any] = []
    try:
        for lock in locks:
            remaining = max(0.0, deadline - time.monotonic())
            if not lock.acquire(timeout=remaining):
                yield False
                return
            acquired.append(lock)
        yield True
    finally:
        for lock in reversed(acquired):
            lock.release()


def uses_torch_cuda(backend: str | None, device: str | None) -> bool:
    normalized_backend = str(backend or "").strip().lower()
    normalized_device = str(device or "").strip().lower()
    return normalized_backend in {"torch", "sentence-transformers"} and normalized_device.startswith("cuda")


def load_model(owner: Any, *, uses_cuda: bool, factory: Callable[[], Any]) -> Any:
    if not uses_cuda:
        return factory()
    with _CUDA_MODEL_LOCK:
        model = factory()
        _CUDA_MODELS.add(owner)
        return model


def release_model(owner: Any, *, used_cuda: bool) -> bool:
    if not used_cuda:
        return False
    with _CUDA_MODEL_LOCK:
        if owner not in _CUDA_MODELS:
            return False
        _CUDA_MODELS.discard(owner)
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
