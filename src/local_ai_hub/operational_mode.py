from __future__ import annotations

import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


VALID_MODES = frozenset({"active", "gaming", "maintenance"})
_REPLACE_ATTEMPTS = 5
_REPLACE_DELAY_SECONDS = 0.025
_LOCK_TIMEOUT_SECONDS = 5.0
# Mode changes are operator-driven; suggest bounded delayed retry, never immediate spin.
_MODE_RETRY_AFTER_SECONDS = 5
_GAMING_UNLOAD_DEADLINE_SECONDS = 4.0
_GAMING_UNLOAD_REQUEST_TIMEOUT_SECONDS = 0.5
_IN_PROCESS_RELEASE_DEADLINE_SECONDS = 3.0
_thread_locks: dict[str, threading.RLock] = {}
_thread_locks_guard = threading.Lock()
_cuda_cleanup_lock = threading.Lock()


@dataclass(frozen=True)
class OperationalModeSnapshot:
    mode: str
    revision: int
    degraded: bool = False
    error: str = ""


class OperationalModeWriteError(OSError):
    pass


def _resolve_state_dir(state_dir: str | os.PathLike[str] | None = None) -> Path:
    if state_dir is not None:
        return Path(state_dir).expanduser().resolve()
    configured = os.environ.get("LOCAL_AI_STATE_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    try:
        from .config import load_config

        value = load_config().get("server", {}).get("state_dir")
        if value:
            return Path(str(value)).expanduser().resolve()
    except Exception:
        pass
    return (Path.home() / ".local-ai-hub" / "state").resolve()


def _paths(state_dir: str | os.PathLike[str] | None = None) -> tuple[Path, Path]:
    directory = _resolve_state_dir(state_dir)
    return directory / "operational_mode.json", directory / "operational_mode.lock"


def _thread_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _thread_locks_guard:
        return _thread_locks.setdefault(key, threading.RLock())


@contextmanager
def _file_lock(path: Path, timeout: float = _LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    """Serialize writers across threads and processes without a third-party lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    local_lock = _thread_lock(path)
    deadline = time.monotonic() + max(0.05, float(timeout))
    with local_lock:
        with path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            acquired = False
            while not acquired:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except (OSError, BlockingIOError):
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"timed out acquiring operational mode lock: {path}")
                    time.sleep(0.025)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_unlocked(path: Path) -> OperationalModeSnapshot:
    if not path.exists():
        legacy_path = path.with_name("operational-mode.json")
        if legacy_path.exists():
            return OperationalModeSnapshot(
                "maintenance",
                -1,
                True,
                "legacy operational mode state filename; explicitly set a mode to recover",
            )
        return OperationalModeSnapshot("active", 0)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        mode = str(payload.get("mode", "")).strip().lower()
        revision = int(payload.get("revision", 0))
        if mode not in VALID_MODES or revision < 0:
            raise ValueError("invalid mode or revision")
        return OperationalModeSnapshot(mode, revision)
    except Exception as exc:
        return OperationalModeSnapshot(
            "maintenance", -1, True, f"invalid operational mode state: {str(exc)[:180]}"
        )


def load_operational_mode(
    state_dir: str | os.PathLike[str] | None = None,
) -> OperationalModeSnapshot:
    state_path, lock_path = _paths(state_dir)
    with _file_lock(lock_path):
        return _read_unlocked(state_path)


def _replace_with_retry(source: Path, target: Path) -> None:
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except OSError as exc:
            windows_lock_conflict = os.name == "nt" and getattr(exc, "winerror", None) in {32, 33}
            if not isinstance(exc, PermissionError) and not windows_lock_conflict:
                raise
            if attempt + 1 >= _REPLACE_ATTEMPTS:
                raise
            time.sleep(_REPLACE_DELAY_SECONDS * (2**attempt))


def _write_unlocked(path: Path, snapshot: OperationalModeSnapshot) -> None:
    temp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    payload = json.dumps(
        {"mode": snapshot.mode, "revision": snapshot.revision},
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
    try:
        with temp_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(temp_path, path)
    except Exception as exc:
        raise OperationalModeWriteError(f"cannot persist operational mode: {exc}") from exc
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def set_operational_mode(
    state_dir: str | os.PathLike[str] | None,
    mode: str,
) -> OperationalModeSnapshot:
    normalized = str(mode or "").strip().lower()
    if normalized not in VALID_MODES:
        raise ValueError(f"invalid operational mode: {mode!r}")
    state_path, lock_path = _paths(state_dir)
    with _file_lock(lock_path):
        current = _read_unlocked(state_path)
        snapshot = OperationalModeSnapshot(normalized, max(0, current.revision) + 1)
        _write_unlocked(state_path, snapshot)
        return snapshot


def operational_mode_gate_error(
    snapshot: Any,
    action: str | None = None,
    *,
    requires_heavy_work: bool = True,
) -> dict[str, Any] | None:
    """Return a rejection for expensive work while preserving deterministic reads.

    MCP callers classify an action before invoking this helper and pass
    ``requires_heavy_work=False`` for bounded deterministic/indexed reads. Async
    job callers keep the default because their mode-specific action allowlist has
    already decided that the action is blocked.
    """
    mode = str(getattr(snapshot, "mode", "maintenance") or "maintenance").lower()
    degraded = bool(getattr(snapshot, "degraded", True))
    if not degraded and mode == "active":
        return None
    if not degraded and mode == "gaming" and (
        not requires_heavy_work or action == "speculative_lint"
    ):
        return None
    detail = "state unavailable; fail closed" if degraded else f"mode is {mode}"
    return {
        "success": False,
        "error": f"operation blocked by operational mode ({detail})",
        "error_code": "operational_mode_blocked",
        "operational_mode": mode,
        "operational_mode_degraded": degraded,
        "action": str(action or ""),
        "retryable": True,
        "terminal": False,
        "retry_after_seconds": _MODE_RETRY_AFTER_SECONDS,
    }


def unload_ollama_models_for_gaming(
    runtime: Any,
    *,
    inference_active: bool,
    timeout_seconds: float | None = None,
    should_stop: Any = None,
) -> dict[str, Any]:
    """Delegate bounded loaded-model cancellation/unload to the Ollama owner."""
    started_at = time.monotonic()
    try:
        requested_timeout = (
            _GAMING_UNLOAD_DEADLINE_SECONDS
            if timeout_seconds is None
            else max(0.0, float(timeout_seconds))
        )
    except (TypeError, ValueError):
        requested_timeout = _GAMING_UNLOAD_DEADLINE_SECONDS
    deadline_seconds = min(requested_timeout, _GAMING_UNLOAD_DEADLINE_SECONDS)
    deadline = started_at + deadline_seconds

    def result(state: str, reason: str, **extra: Any) -> dict[str, Any]:
        return {
            "success": state in {"complete", "not_applicable"},
            "state": state,
            "reason": reason,
            "unloaded": [],
            "remaining": [],
            "pending": [],
            "verified": False,
            "deadline_seconds": deadline_seconds,
            "elapsed_seconds": max(0.0, time.monotonic() - started_at),
            **extra,
        }

    if not bool(getattr(runtime, "config", {}).get("ollama", {}).get("enabled", False)):
        return result("not_applicable", "ollama_backend_disabled")
    if inference_active:
        return result("deferred", "inference_active")
    if callable(should_stop) and should_stop():
        return result("cancelled", "gaming_release_cancelled", cancelled=True)

    unload = getattr(runtime, "unload_configured_models", None)
    if not callable(unload):
        return result("failed", "ollama_release_owner_unavailable", error="unload_configured_models unavailable")
    if deadline_seconds <= 0:
        return result("timed_out", "unload_deadline_exceeded")
    try:
        raw = unload(
            timeout_seconds=deadline_seconds,
            should_stop=should_stop,
            deadline=deadline,
        )
    except Exception as exc:
        return result("failed", "ollama_release_failed", error=str(exc)[:240])
    if not isinstance(raw, dict):
        return result("failed", "invalid_ollama_release_receipt")

    unloaded = raw.get("unloaded") if isinstance(raw.get("unloaded"), list) else []
    failed = raw.get("failed")
    cancelled = raw.get("cancelled") is True or (
        isinstance(failed, dict) and "cancel" in str(failed.get("operation", "")).lower()
    )
    failure_text = " ".join(str(value) for value in failed.values()).lower() if isinstance(failed, dict) else ""
    timed_out = bool(raw.get("timed_out")) or "deadline" in failure_text or "timed out" in failure_text
    owner_success = raw.get("success") is True and not failed
    raw_remaining = raw.get("remaining")
    remaining_is_list = isinstance(raw_remaining, list)
    remaining = list(raw_remaining) if remaining_is_list else None
    verified = raw.get("verified") is True
    unverified = raw.get("unverified") is True or not remaining_is_list
    success = owner_success and verified and not remaining and not unverified
    if cancelled:
        state, reason = "cancelled", "gaming_release_cancelled"
    elif timed_out:
        state, reason = "timed_out", "unload_deadline_exceeded"
    elif unverified:
        state, reason = "unverified", "post_unload_inventory_unavailable"
    elif owner_success and not unloaded and verified and not remaining:
        state, reason = "not_applicable", "no_configured_models_loaded"
    elif success:
        state, reason = "complete", "loaded_models_absence_verified"
    elif owner_success and not verified:
        state, reason = "requested", "unload_acknowledged_but_not_verified"
    else:
        state, reason = "partial", "unload_incomplete"
    return {
        "success": success,
        "state": state,
        "reason": reason,
        "unloaded": [str(item) for item in unloaded],
        "requested": raw.get("requested", []),
        "remaining": remaining,
        "complete": raw.get("complete") is True,
        "unverified": unverified,
        "physical_vram_reclaimed": False,
        "pending": raw.get("pending", []),
        "failures": failed if isinstance(failed, dict) else {},
        "verified": verified,
        "deadline_seconds": deadline_seconds,
        "elapsed_seconds": max(0.0, time.monotonic() - started_at),
        "owner_receipt": raw,
    }


def _begin_resource_release(release_lifecycle: Any) -> str | None:
    begin = getattr(release_lifecycle, "begin_resource_release", None)
    return str(begin()) if callable(begin) else None


def _end_resource_release(release_lifecycle: Any, token: str | None) -> None:
    finish = getattr(release_lifecycle, "end_resource_release", None)
    if token and callable(finish):
        try:
            finish(token)
        except Exception:
            pass


def _register_resource_release_worker(
    release_lifecycle: Any,
    token: str | None,
    worker: threading.Thread,
) -> None:
    register = getattr(release_lifecycle, "register_resource_release_worker", None)
    if token and callable(register):
        if register(token, worker) is False:
            raise RuntimeError("resource release worker ownership unavailable")


def _empty_torch_cuda_cache(
    timeout_seconds: float,
    *,
    release_lifecycle: Any = None,
) -> dict[str, Any]:
    if timeout_seconds <= 0:
        return {"success": False, "state": "deadline_exceeded", "verified": False}
    if not _cuda_cleanup_lock.acquire(blocking=False):
        return {"success": False, "state": "busy", "verified": False}

    try:
        release_token = _begin_resource_release(release_lifecycle)
    except Exception as exc:
        _cuda_cleanup_lock.release()
        return {"success": False, "state": "failed", "error": str(exc)[:160], "verified": False}

    result: dict[str, Any] = {}
    finished = threading.Event()

    def cleanup() -> None:
        try:
            try:
                import torch
            except Exception as exc:
                result.update({"success": False, "state": "unavailable", "error": str(exc)[:160], "verified": False})
                return
            cuda = getattr(torch, "cuda", None)
            if cuda is None or not callable(getattr(cuda, "is_available", None)):
                result.update({"success": False, "state": "unavailable", "reason": "torch_cuda_api_missing", "verified": False})
                return
            try:
                if not cuda.is_available():
                    result.update({"success": False, "state": "unavailable", "reason": "cuda_not_available_after_cuda_model_release", "verified": False})
                    return
                if not callable(getattr(cuda, "empty_cache", None)):
                    result.update({"success": False, "state": "unavailable", "reason": "torch_cuda_empty_cache_missing", "verified": False})
                    return
                cuda.empty_cache()
                result.update({"success": True, "state": "requested", "verified": False})
            except Exception as exc:
                result.update({"success": False, "state": "failed", "error": str(exc)[:160], "verified": False})
        finally:
            _cuda_cleanup_lock.release()
            _end_resource_release(release_lifecycle, release_token)
            finished.set()

    try:
        worker = threading.Thread(
            target=cleanup, name="local-ai-cuda-cache-cleanup", daemon=True
        )
        _register_resource_release_worker(release_lifecycle, release_token, worker)
        worker.start()
    except Exception as exc:
        _cuda_cleanup_lock.release()
        _end_resource_release(release_lifecycle, release_token)
        return {"success": False, "state": "failed", "error": str(exc)[:160], "verified": False}
    if not finished.wait(timeout_seconds):
        return {"success": False, "state": "deadline_exceeded", "verified": False}
    return result


def _release_accelerator_bounded(
    component: Any,
    timeout_seconds: float,
    *,
    release_lifecycle: Any = None,
) -> dict[str, Any]:
    if timeout_seconds <= 0:
        return {
            "success": False, "state": "timed_out", "status": "timed_out",
            "released": False, "verified": False,
        }
    try:
        release_token = _begin_resource_release(release_lifecycle)
    except Exception as exc:
        return {
            "success": False, "state": "error", "status": "error",
            "released": False, "error": str(exc)[:160], "verified": False,
        }
    finished = threading.Event()
    result: dict[str, Any] = {}

    def run_release() -> None:
        try:
            try:
                status_fn = getattr(component, "status", None)
                release_fn = getattr(component, "release", None)
                if not callable(release_fn):
                    release_fn = getattr(component, "release_accelerator", None)
                if not callable(status_fn) or not callable(release_fn):
                    result.update({
                        "success": False, "state": "error", "status": "error",
                        "released": False, "reason": "release_or_status_unavailable",
                        "verified": False,
                    })
                    return

                before = status_fn()
                if not isinstance(before, dict) or not isinstance(before.get("loaded"), bool):
                    result.update({
                        "success": False, "state": "error", "status": "error",
                        "released": False, "reason": "invalid_pre_release_status",
                        "verified": False,
                    })
                    return
                backend = str(before.get("active_backend") or before.get("backend") or "")
                device = str(before.get("active_device") or before.get("device") or "")
                base = {
                    "backend": backend,
                    "device": device,
                    "released": False,
                    "vram_release": None,
                    "verified": False,
                }
                if not before["loaded"]:
                    result.update({**base, "success": True, "state": "not_loaded", "status": "not_loaded"})
                    return
                backend_key = backend.strip().lower()
                device_key = device.strip().lower()
                if backend_key == "ollama" or device_key == "ollama":
                    result.update({
                        **base, "success": True, "state": "external_backend",
                        "status": "external_backend", "reason": "managed_by_ollama",
                    })
                    return
                if device_key == "cpu" or device_key.startswith("cpu:"):
                    result.update({
                        **base, "success": True, "state": "cpu_noop",
                        "status": "cpu_noop", "reason": "no_accelerator_resource",
                    })
                    return

                value = release_fn(timeout_seconds=timeout_seconds)
                after = status_fn()
                if not isinstance(after, dict) or not isinstance(after.get("loaded"), bool):
                    result.update({
                        **base, "success": False, "state": "error", "status": "error",
                        "reason": "invalid_post_release_status",
                    })
                    return
                reported_cuda_possible = value.get("cuda_memory_possible") if isinstance(value, dict) else None
                cuda_memory_possible = (
                    bool(reported_cuda_possible)
                    if isinstance(reported_cuda_possible, bool)
                    else "cuda" in device_key and backend_key != "openvino"
                )
                cache_receipt = after.get("cache_cleanup")
                if not isinstance(cache_receipt, dict):
                    cache_receipt = {"success": None, "state": "not_reported", "verified": False}
                release_ok = value is True or (
                    isinstance(value, dict)
                    and value.get("success") is True
                    and value.get("state") in {"unloaded", "released", "not_applicable"}
                )
                owner_state = value.get("state") if isinstance(value, dict) else None
                if owner_state == "not_applicable":
                    result.update({
                        **base, "success": True, "state": "not_applicable", "status": "not_applicable",
                        "reason": "component_reported_no_accelerator_model",
                        "cuda_memory_possible": False,
                        "cache_cleanup": {"success": True, "state": "not_applicable", "verified": False},
                    })
                elif release_ok and not after["loaded"]:
                    result.update({
                        **base, "success": True, "state": "released", "status": "released",
                        "released": True, "cuda_memory_possible": cuda_memory_possible,
                        "cache_cleanup": cache_receipt if cuda_memory_possible else {"success": True, "state": "not_applicable", "verified": False},
                    })
                elif not after["loaded"]:
                    result.update({
                        **base, "success": True, "state": "not_loaded", "status": "not_loaded",
                        "reason": "model_was_already_detached",
                    })
                elif value is False or (isinstance(value, dict) and value.get("success") is not True):
                    timeout_state = owner_state in {"busy", "timed_out", "deadline_exceeded"}
                    result.update({
                        **base,
                        "success": False,
                        "state": "timed_out" if timeout_state or value is False else "error",
                        "status": "timed_out" if timeout_state or value is False else "error",
                        "reason": "release_returned_false_while_model_remained_loaded" if value is False else str(owner_state or "release_failed"),
                        "cuda_memory_possible": cuda_memory_possible,
                        "cache_cleanup": cache_receipt if cuda_memory_possible else {"success": True, "state": "not_applicable", "verified": False},
                    })
                else:
                    result.update({
                        **base, "success": False, "state": "error", "status": "error",
                        "reason": "model_remained_loaded_after_release",
                        "cuda_memory_possible": cuda_memory_possible,
                        "cache_cleanup": cache_receipt if cuda_memory_possible else {"success": True, "state": "not_applicable", "verified": False},
                    })
            except Exception as exc:
                result.update({
                    "success": False, "state": "error", "status": "error",
                    "released": False, "error": str(exc)[:160], "verified": False,
                })
        finally:
            _end_resource_release(release_lifecycle, release_token)
            finished.set()

    try:
        worker = threading.Thread(
            target=run_release, name="local-ai-accelerator-release", daemon=True
        )
        _register_resource_release_worker(release_lifecycle, release_token, worker)
        worker.start()
    except Exception as exc:
        _end_resource_release(release_lifecycle, release_token)
        return {
            "success": False, "state": "error", "status": "error",
            "released": False, "error": str(exc)[:160], "verified": False,
        }
    if not finished.wait(timeout_seconds):
        return {
            "success": False, "state": "timed_out", "status": "timed_out",
            "released": False, "pending": True, "verified": False,
        }
    return result


def unload_in_process_accelerators_for_gaming(
    embeddings: Any = None,
    reranker: Any = None,
    *,
    inference_active: bool,
    timeout_seconds: float | None = None,
    release_lifecycle: Any = None,
) -> dict[str, Any]:
    """Release resident local accelerator models within a bounded lock budget.

    Successful calls report observed model detachment and any cache receipt
    supplied by the owning component. They never claim measured physical VRAM release.
    """
    started_at = time.monotonic()
    try:
        requested = _IN_PROCESS_RELEASE_DEADLINE_SECONDS if timeout_seconds is None else max(0.0, float(timeout_seconds))
    except (TypeError, ValueError):
        requested = _IN_PROCESS_RELEASE_DEADLINE_SECONDS
    deadline_seconds = min(requested, _IN_PROCESS_RELEASE_DEADLINE_SECONDS)
    deadline = started_at + deadline_seconds

    def remaining_seconds() -> float:
        return max(0.0, deadline - time.monotonic())

    if inference_active:
        return {
            "success": False,
            "state": "deferred",
            "status": "deferred",
            "reason": "inference_active",
            "models": {},
            "cuda_cleanup": {"success": False, "state": "deferred", "status": "deferred", "verified": False},
            "verified": False,
            "deadline_seconds": deadline_seconds,
            "elapsed_seconds": max(0.0, time.monotonic() - started_at),
        }

    models: dict[str, dict[str, Any]] = {}
    cuda_memory_possible = False
    any_unloaded = False
    release_pending = False
    for label, component in (("embeddings", embeddings), ("reranker", reranker)):
        if component is None:
            continue
        budget = remaining_seconds()
        if budget <= 0:
            models[label] = {
                "success": False, "state": "timed_out", "status": "timed_out",
                "released": False, "verified": False,
            }
            continue
        result = _release_accelerator_bounded(
            component, budget, release_lifecycle=release_lifecycle
        )
        models[label] = dict(result)
        any_unloaded = any_unloaded or result.get("released") is True
        release_pending = release_pending or bool(result.get("pending"))
        cuda_memory_possible = cuda_memory_possible or bool(result.get("cuda_memory_possible"))

    cuda_items = [
        item for item in models.values()
        if item.get("cuda_memory_possible") is True
    ]
    if release_pending:
        cache_result = {
            "success": False, "state": "deferred", "status": "deferred",
            "reason": "model_release_still_running", "verified": False,
        }
    elif cuda_items:
        receipts = [item.get("cache_cleanup") for item in cuda_items]
        receipts = [item for item in receipts if isinstance(item, dict)]
        if receipts and all(item.get("state") == receipts[0].get("state") for item in receipts):
            cache_result = dict(receipts[0])
        else:
            cache_result = {
                "success": None, "state": "component_managed", "status": "component_managed",
                "verified": False,
            }
    else:
        cache_result = {
            "success": True, "state": "not_applicable", "status": "not_applicable",
            "verified": False,
        }

    failures = [name for name, item in models.items() if item.get("success") is not True]
    if cache_result.get("success") is False and cache_result.get("state") != "deferred":
        failures.append("cuda_cleanup")
    success = not failures
    if not models:
        state = "not_applicable"
    elif success:
        state = "complete" if any_unloaded else "not_applicable"
    else:
        state = "partial" if any_unloaded else "failed"
    return {
        "success": success,
        "state": state,
        "status": state,
        "reason": "model_references_released" if any_unloaded else "no_in_process_accelerator_model",
        "models": models,
        "cuda_cleanup": dict(cache_result),
        "failures": failures,
        "verified": False,
        "vram_release": None,
        "deadline_seconds": deadline_seconds,
        "elapsed_seconds": max(0.0, time.monotonic() - started_at),
    }
