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
    return directory / "operational-mode.json", directory / "operational-mode.lock"


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
    mode: str,
    state_dir: str | os.PathLike[str] | None = None,
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
    if not requires_heavy_work:
        return None
    mode = str(getattr(snapshot, "mode", "maintenance") or "maintenance").lower()
    degraded = bool(getattr(snapshot, "degraded", True))
    if not degraded and mode == "active":
        return None
    if not degraded and mode == "gaming" and action == "speculative_lint":
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
) -> dict[str, Any]:
    """Unload resident models, or truthfully defer while inference is still active."""
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

    def elapsed() -> float:
        return max(0.0, time.monotonic() - started_at)

    def request_timeout(reserve_seconds: float = 0.0) -> float:
        budget = min(
            _GAMING_UNLOAD_REQUEST_TIMEOUT_SECONDS,
            deadline - time.monotonic() - reserve_seconds,
        )
        if budget <= 0:
            raise TimeoutError("gaming model unload deadline reached")
        return budget

    if not bool(getattr(runtime, "config", {}).get("ollama", {}).get("enabled", False)):
        return {
            "success": False,
            "state": "not_applicable",
            "reason": "ollama_backend_disabled",
            "unloaded": [],
            "remaining": [],
            "pending": [],
            "verified": False,
            "deadline_seconds": deadline_seconds,
            "elapsed_seconds": elapsed(),
        }

    fast_runtime = getattr(runtime, "fast", None)
    smart_runtime = getattr(runtime, "smart", None)
    if fast_runtime is not None and smart_runtime is not None:
        targets = [("fast", fast_runtime), ("smart", smart_runtime)]
    else:
        targets = [("", runtime)]

    def inventory() -> dict[str, tuple[Any, str]]:
        entries: dict[str, tuple[Any, str]] = {}
        for index, (endpoint, target) in enumerate(targets):
            reserve = (len(targets) - index - 1) * _GAMING_UNLOAD_REQUEST_TIMEOUT_SECONDS
            response = target.request("/api/ps", timeout=request_timeout(reserve))
            if not isinstance(response, dict) or "error" in response:
                detail = response.get("error", "invalid Ollama inventory response") if isinstance(response, dict) else "invalid Ollama inventory response"
                raise RuntimeError(f"{endpoint or 'ollama'}: {detail}")
            if "models" not in response:
                raise RuntimeError(f"{endpoint or 'ollama'}: Ollama inventory omitted models")
            rows = response["models"]
            if not isinstance(rows, list):
                raise RuntimeError(f"{endpoint or 'ollama'}: invalid Ollama inventory response")
            for row in rows:
                if not isinstance(row, dict):
                    raise RuntimeError(f"{endpoint or 'ollama'}: invalid model row in Ollama inventory")
                raw_name = row.get("name")
                if not isinstance(raw_name, str) or not raw_name.strip():
                    raw_name = row.get("model")
                name = str(raw_name or "").strip()
                if not name:
                    raise RuntimeError(f"{endpoint or 'ollama'}: model row omitted name and model")
                label = f"{endpoint}:{name}" if endpoint else name
                entries[label] = (target, name)
        return dict(sorted(entries.items()))

    try:
        entries = inventory()
    except Exception as exc:
        deadline_expired = isinstance(exc, TimeoutError) or "timed out" in str(exc).lower()
        return {
            "success": False,
            "state": "unknown" if deadline_expired else "failed",
            "reason": (
                "unload_deadline_exceeded"
                if deadline_expired
                else "model_inventory_unavailable"
            ),
            "error": str(exc)[:240],
            "unloaded": [],
            "remaining": [],
            "pending": [],
            "verified": False,
            "deadline_seconds": deadline_seconds,
            "elapsed_seconds": elapsed(),
        }
    if inference_active:
        return {
            "success": False,
            "state": "deferred",
            "reason": "inference_active",
            "unloaded": [],
            "remaining": list(entries),
            "pending": list(entries),
            "verified": True,
            "deadline_seconds": deadline_seconds,
            "elapsed_seconds": elapsed(),
        }
    unloaded: list[str] = []
    failures: dict[str, str] = {}
    pending: list[str] = []
    verification_reserve = len(targets) * _GAMING_UNLOAD_REQUEST_TIMEOUT_SECONDS
    for index, (label, (target, name)) in enumerate(entries.items()):
        try:
            timeout = request_timeout(verification_reserve)
        except TimeoutError:
            pending = list(entries)[index:]
            for pending_label in pending:
                failures[pending_label] = "unload deadline reached"
            break
        try:
            if target.unload_model(name, timeout=timeout):
                unloaded.append(label)
            else:
                failures[label] = "unload returned false"
        except Exception as exc:
            failures[label] = str(exc)[:200]
    try:
        remaining_entries = inventory()
    except Exception as exc:
        deadline_expired = isinstance(exc, TimeoutError) or "timed out" in str(exc).lower()
        return {
            "success": False,
            "state": "unknown",
            "reason": (
                "unload_deadline_exceeded"
                if deadline_expired
                else "post_unload_inventory_unavailable"
            ),
            "error": str(exc)[:240],
            "unloaded": unloaded,
            "remaining": sorted(set(entries) - set(unloaded)),
            "pending": pending,
            "failures": failures,
            "verified": False,
            "deadline_seconds": deadline_seconds,
            "elapsed_seconds": elapsed(),
        }
    remaining = list(remaining_entries)
    success = not remaining and not failures
    return {
        "success": success,
        "state": "complete" if success else "partial",
        "reason": (
            "all_models_unloaded"
            if success
            else "unload_deadline_exceeded"
            if pending
            else "unload_incomplete"
        ),
        "unloaded": unloaded,
        "remaining": remaining,
        "pending": pending,
        "failures": failures,
        "verified": True,
        "deadline_seconds": deadline_seconds,
        "elapsed_seconds": elapsed(),
    }


def _empty_torch_cuda_cache(timeout_seconds: float) -> dict[str, Any]:
    if timeout_seconds <= 0:
        return {"success": False, "state": "deadline_exceeded", "verified": False}
    if not _cuda_cleanup_lock.acquire(blocking=False):
        return {"success": False, "state": "busy", "verified": False}

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
            finished.set()

    try:
        threading.Thread(target=cleanup, name="local-ai-cuda-cache-cleanup", daemon=True).start()
    except Exception as exc:
        _cuda_cleanup_lock.release()
        return {"success": False, "state": "failed", "error": str(exc)[:160], "verified": False}
    if not finished.wait(timeout_seconds):
        return {"success": False, "state": "deadline_exceeded", "verified": False}
    return result


def _release_accelerator_bounded(release: Any, timeout_seconds: float) -> dict[str, Any]:
    if timeout_seconds <= 0:
        return {"success": False, "state": "deadline_exceeded", "verified": False}
    finished = threading.Event()
    result: dict[str, Any] = {}

    def run_release() -> None:
        try:
            try:
                value = release(timeout_seconds=timeout_seconds)
                result.update(value if isinstance(value, dict) else {
                    "success": False, "state": "invalid_result", "verified": False,
                })
            except Exception as exc:
                result.update({
                    "success": False, "state": "failed", "error": str(exc)[:160], "verified": False,
                })
        finally:
            finished.set()

    try:
        threading.Thread(target=run_release, name="local-ai-accelerator-release", daemon=True).start()
    except Exception as exc:
        return {"success": False, "state": "failed", "error": str(exc)[:160], "verified": False}
    if not finished.wait(timeout_seconds):
        return {"success": False, "state": "deadline_exceeded", "verified": False}
    return result


def unload_in_process_accelerators_for_gaming(
    embeddings: Any = None,
    reranker: Any = None,
    *,
    inference_active: bool,
    timeout_seconds: float | None = None,
    cuda_cleanup: Any = None,
) -> dict[str, Any]:
    """Release resident local accelerator models within a bounded lock budget.

    Successful calls report that model references were released or CUDA cache
    cleanup was requested. They never claim measured physical VRAM release.
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
            "reason": "inference_active",
            "models": {},
            "cuda_cleanup": {"success": False, "state": "deferred", "verified": False},
            "verified": False,
            "deadline_seconds": deadline_seconds,
            "elapsed_seconds": max(0.0, time.monotonic() - started_at),
        }

    models: dict[str, dict[str, Any]] = {}
    cuda_memory_possible = False
    any_unloaded = False
    for label, component in (("embeddings", embeddings), ("reranker", reranker)):
        if component is None:
            continue
        release = getattr(component, "release_accelerator", None)
        if not callable(release):
            models[label] = {"success": False, "state": "unsupported", "verified": False}
            continue
        budget = remaining_seconds()
        if budget <= 0:
            models[label] = {"success": False, "state": "deadline_exceeded", "verified": False}
            continue
        result = _release_accelerator_bounded(release, budget)
        models[label] = dict(result)
        any_unloaded = any_unloaded or result.get("state") == "unloaded"
        cuda_memory_possible = cuda_memory_possible or bool(result.get("cuda_memory_possible"))

    if cuda_memory_possible:
        budget = remaining_seconds()
        try:
            cache_result = (
                cuda_cleanup(timeout_seconds=budget)
                if callable(cuda_cleanup)
                else _empty_torch_cuda_cache(budget)
            )
            if not isinstance(cache_result, dict):
                cache_result = {"success": False, "state": "invalid_result", "verified": False}
        except Exception as exc:
            cache_result = {"success": False, "state": "failed", "error": str(exc)[:160], "verified": False}
    else:
        cache_result = {"success": True, "state": "not_applicable", "verified": False}

    failures = [name for name, item in models.items() if item.get("success") is not True]
    if cache_result.get("success") is not True:
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
        "reason": "model_references_released" if any_unloaded else "no_in_process_accelerator_model",
        "models": models,
        "cuda_cleanup": dict(cache_result),
        "failures": failures,
        "verified": False,
        "deadline_seconds": deadline_seconds,
        "elapsed_seconds": max(0.0, time.monotonic() - started_at),
    }
