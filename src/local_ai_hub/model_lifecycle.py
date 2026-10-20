from __future__ import annotations

from contextlib import contextmanager
import gc
import math
import numbers
import threading
import time
from typing import Any, Callable
import weakref


_CUDA_MODEL_LOCK = threading.RLock()
_CUDA_MODELS: weakref.WeakSet[Any] = weakref.WeakSet()
_CUDA_PROCESS_MODELS: weakref.WeakKeyDictionary[Any, Any] = weakref.WeakKeyDictionary()
_MAX_LOCK_TIMEOUT_SECONDS = 86_400.0
_METRICS_LOCK = threading.Lock()
_METRICS: dict[str, Any] = {"lock_wait_seconds": 0.0, "operation_seconds": 0.0,
    "acquire_timeouts": 0, "operations": 0, "active_operation": "", "active_since": 0.0}


def lifecycle_status() -> dict[str, Any]:
    """Observe even a blocked driver without acquiring the CUDA lifecycle lock."""
    with _METRICS_LOCK:
        result = dict(_METRICS)
    started = result.pop("active_since")
    result["active_age_seconds"] = max(0.0, time.monotonic() - started) if started else 0.0
    result["execution_boundary"] = "caller_process"
    result["driver_call_preemptible"] = False
    result["cuda_nlp_execution_boundary"] = "owned_process_with_timeout_and_reap"
    return result


@contextmanager
def _cuda_guard(operation: str, timeout_seconds: float = 5.0):
    started = time.monotonic()
    with acquire_locks((_CUDA_MODEL_LOCK,), timeout_seconds) as acquired:
        entered = time.monotonic()
        with _METRICS_LOCK:
            _METRICS["lock_wait_seconds"] += entered - started
            if not acquired:
                _METRICS["acquire_timeouts"] += 1
        if not acquired:
            raise TimeoutError("CUDA lifecycle lock timed out")
        with _METRICS_LOCK:
            previous = (_METRICS["active_operation"], _METRICS["active_since"])
            _METRICS["active_operation"], _METRICS["active_since"] = operation, entered
        try:
            yield
        finally:
            with _METRICS_LOCK:
                _METRICS["operation_seconds"] += time.monotonic() - entered
                _METRICS["operations"] += 1
                _METRICS["active_operation"], _METRICS["active_since"] = previous


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
def acquire_locks(locks: tuple[Any, ...], timeout_seconds: float):
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, numbers.Real):
        raise ValueError("timeout_seconds must be a finite nonnegative real number")
    try:
        timeout = float(timeout_seconds)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("timeout_seconds must be a finite nonnegative real number") from exc
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError("timeout_seconds must be a finite nonnegative real number")

    timeout = min(timeout, threading.TIMEOUT_MAX)
    deadline = time.monotonic() + timeout
    acquired: list[Any] = []
    seen: set[int] = set()
    try:
        for lock in locks:
            identity = id(lock)
            if identity in seen:
                continue
            seen.add(identity)
            remaining = min(max(0.0, deadline - time.monotonic()), threading.TIMEOUT_MAX)
            if not lock.acquire(timeout=remaining):
                yield False
                return
            acquired.append(lock)
        yield True
    finally:
        for lock in reversed(acquired):
            lock.release()


def uses_torch_cuda(backend: str | None, device: str | None) -> bool:
    if not isinstance(backend, str) or not isinstance(device, str) or "\x00" in backend or "\x00" in device:
        return False
    normalized_backend = backend.strip().lower()
    normalized_device = device.strip().lower()
    return normalized_backend in {"torch", "sentence-transformers"} and normalized_device.startswith("cuda")


def active_cuda_model_count(*, lock_timeout_seconds: float = 5.0) -> int:
    with _cuda_guard("count", lock_timeout_seconds):
        return len(_CUDA_MODELS)


def is_cuda_model_registered(owner: Any, *, lock_timeout_seconds: float = 5.0) -> bool:
    if owner is None:
        return False
    with _cuda_guard("registered", lock_timeout_seconds):
        try:
            return owner in _CUDA_MODELS
        except TypeError:
            return False


def load_model(owner: Any, *, uses_cuda: bool, factory: Callable[[], Any], lock_timeout_seconds: float = 5.0) -> Any:
    """Bound acquisition; a hard factory deadline requires an owned process boundary."""
    if not uses_cuda:
        return factory()
    with _cuda_guard("load", lock_timeout_seconds):
        already_tracked = owner in _CUDA_MODELS
        if not already_tracked:
            _CUDA_MODELS.add(owner)
        try:
            model = factory()
            if getattr(model, "owned_process", False) is True:
                _CUDA_PROCESS_MODELS[owner] = model
            return model
        except BaseException:
            if not already_tracked:
                _CUDA_MODELS.discard(owner)
            raise


def release_model(owner: Any, *, used_cuda: bool, lock_timeout_seconds: float = 5.0) -> bool:
    if not used_cuda:
        return False
    with _cuda_guard("release", lock_timeout_seconds):
        try:
            if owner not in _CUDA_MODELS:
                return False
            owned = _CUDA_PROCESS_MODELS.get(owner)
            if owned is not None:
                # Keep ownership and registration if process reaping fails.
                owned.close()
                del _CUDA_PROCESS_MODELS[owner]
                _CUDA_MODELS.discard(owner)
                return True
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
