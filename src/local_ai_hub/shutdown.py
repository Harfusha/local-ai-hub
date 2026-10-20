"""Owned, bounded waiting for sequential idempotent component cleanup."""
from __future__ import annotations

import math
import threading
from typing import Any, Callable


class CloseCoordinator:
    """A timeout reports pending work; it never pretends to kill a callback thread."""
    def __init__(self, steps: list[tuple[str, Callable[[], Any]]]):
        self._steps = tuple(steps)
        self._states = {name: {"state": "pending"} for name, _ in steps}
        self._lock = threading.Lock()
        self._running = False
        self._done = threading.Event()
        self._worker: threading.Thread | None = None

    def _report(self) -> dict[str, Any]:
        with self._lock:
            states = {name: dict(value) for name, value in self._states.items()}
            running = self._running
        failed = [name for name, value in states.items() if value["state"] == "failed"]
        pending = [name for name, value in states.items() if value["state"] in {"running", "pending"}]
        return {"success": not failed and not pending, "settled": not running,
                "failed": failed, "pending": pending, "components": states,
                "worker_running": running, "resource_confirmation": "component_close_contracts"}

    def _run(self, done: threading.Event) -> None:
        try:
            for name, callback in self._steps:
                with self._lock:
                    if self._states[name]["state"] == "completed":
                        continue
                    self._states[name] = {"state": "running"}
                try:
                    result = callback()
                    if isinstance(result, dict) and (result.get("success") is False or result.get("cleanup_unconfirmed") is True):
                        raise RuntimeError("component reported incomplete cleanup")
                except BaseException as exc:
                    with self._lock:
                        self._states[name] = {"state": "failed", "error_type": type(exc).__name__}
                else:
                    with self._lock:
                        self._states[name] = {"state": "completed"}
        finally:
            with self._lock:
                self._running = False
            done.set()

    def close(self, timeout: float = 5.0) -> dict[str, Any]:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout < 0:
            raise ValueError("close timeout must be finite and nonnegative")
        with self._lock:
            incomplete = any(state["state"] != "completed" for state in self._states.values())
            if not self._running and incomplete:
                self._running = True
                self._done = threading.Event()
                done = self._done
                self._worker = threading.Thread(target=self._run, args=(done,), name="lah-component-cleanup", daemon=True)
                self._worker.start()
            done, worker = self._done, self._worker
        if worker is not threading.current_thread() and incomplete:
            done.wait(min(float(timeout), 3600.0))
        report = self._report()
        report["timed_out"] = bool(report["pending"])
        return report
