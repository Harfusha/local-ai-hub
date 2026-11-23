"""Continuous FileSystem Watchdog Daemon for immediate incremental preprocessing.

Monitors active workspace roots for file modification, creation, and deletion events.
Debounces burst modifications (e.g. IDE auto-save) with a configurable 500ms window,
then triggers instant incremental preprocessing and cache invalidation before user prompts arrive.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
# import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    _WATCHDOG_AVAILABLE = True
except ImportError:
    Observer = Any  # type: ignore
    FileSystemEventHandler = object  # type: ignore
    _WATCHDOG_AVAILABLE = False

logger = logging.getLogger(__name__)

_DEFAULT_IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    "state",
    ".local-ai-hub",
}


@dataclass(frozen=True)
class WatcherStats:
    """Status metrics of the filesystem watchdog."""

    running: bool
    watched_roots: tuple[str, ...]
    events_received: int
    events_debounced: int
    callbacks_dispatched: int
    watchdog_backend: str


class _DebouncedEventHandler(FileSystemEventHandler):
    """File event handler that coalesces modifications within debounce_window_s."""

    def __init__(
        self,
        root: str,
        callback: Callable[[str, str, str], None],
        debounce_window_s: float = 0.5,
        ignored_dirs: Sequence[str] = (),
    ) -> None:
        super().__init__()
        self.root = os.path.abspath(root)
        self.callback = callback
        self.debounce_window_s = debounce_window_s
        self.ignored_dirs = set(ignored_dirs) or _DEFAULT_IGNORED_DIRS

        self._lock = threading.Lock()
        self._pending_timers: dict[str, threading.Timer] = {}
        self.events_received = 0
        self.events_debounced = 0
        self.callbacks_dispatched = 0

    def _is_ignored(self, path: str) -> bool:
        parts = Path(path).parts
        return any(part in self.ignored_dirs for part in parts)

    def _handle_event(self, event_path: str, change_type: str) -> None:
        if self._is_ignored(event_path):
            return

        with self._lock:
            self.events_received += 1
            norm_path = os.path.abspath(event_path)
            try:
                rel_path = os.path.relpath(norm_path, self.root)
            except ValueError:
                rel_path = norm_path

            # Cancel existing debounce timer for this exact path if active
            if norm_path in self._pending_timers:
                self._pending_timers[norm_path].cancel()
                self.events_debounced += 1

            timer = threading.Timer(
                self.debounce_window_s,
                self._dispatch_debounced,
                args=[norm_path, rel_path, change_type],
            )
            self._pending_timers[norm_path] = timer
            timer.daemon = True
            timer.start()

    def _dispatch_debounced(self, norm_path: str, rel_path: str, change_type: str) -> None:
        with self._lock:
            self._pending_timers.pop(norm_path, None)
            self.callbacks_dispatched += 1

        try:
            self.callback(self.root, rel_path, change_type)
        except Exception as exc:
            logger.warning("Error in watchdog file callback for %s: %s", rel_path, exc)

    def on_modified(self, event: Any) -> None:
        if not getattr(event, "is_directory", False):
            self._handle_event(event.src_path, "modified")

    def on_created(self, event: Any) -> None:
        if not getattr(event, "is_directory", False):
            self._handle_event(event.src_path, "created")

    def on_deleted(self, event: Any) -> None:
        if not getattr(event, "is_directory", False):
            self._handle_event(event.src_path, "deleted")

    def cancel_all(self) -> None:
        with self._lock:
            for timer in self._pending_timers.values():
                timer.cancel()
            self._pending_timers.clear()


class PreprocessWatchdogDaemon:
    """Manages active filesystem observers across one or more workspace roots."""

    def __init__(
        self,
        callback: Callable[[str, str, str], None] | None = None,
        debounce_window_s: float = 0.5,
    ) -> None:
        self.callback = callback or self._default_callback
        self.debounce_window_s = debounce_window_s
        self._observer: Any | None = None
        self._handlers: dict[str, _DebouncedEventHandler] = {}
        self._lock = threading.Lock()
        self._running = False
        self._iocp_watchers: dict[str, Any] = {}
        self._backend = "watchdog" if _WATCHDOG_AVAILABLE else ("iocp" if sys.platform == "win32" else "none")

    @staticmethod
    def _default_callback(root: str, rel_path: str, change_type: str) -> None:
        logger.info("[Watchdog] File %s (%s) in root %s", change_type, rel_path, root)

    def start(self, roots: Sequence[str]) -> bool:
        """Start monitoring the supplied list of directory roots."""
        if not _WATCHDOG_AVAILABLE and sys.platform != "win32":
            logger.warning("watchdog package unavailable and non-Windows platform; watchdog daemon cannot start")
            return False

        with self._lock:
            if self._running:
                return True

            if _WATCHDOG_AVAILABLE:
                self._observer = Observer()
                for r in roots:
                    abs_root = os.path.abspath(r)
                    if os.path.isdir(abs_root) and abs_root not in self._handlers:
                        handler = _DebouncedEventHandler(
                            root=abs_root,
                            callback=self.callback,
                            debounce_window_s=self.debounce_window_s,
                        )
                        self._handlers[abs_root] = handler
                        self._observer.schedule(handler, abs_root, recursive=True)

                self._observer.daemon = True
                self._observer.start()
                self._backend = "watchdog.observers.Observer"
            elif sys.platform == "win32":
                from .iocp_file_watcher import IOCPFileWatcher

                for r in roots:
                    abs_root = os.path.abspath(r)
                    if os.path.isdir(abs_root) and abs_root not in self._iocp_watchers:
                        def make_cb(rt: str):
                            return lambda evt: self.callback(rt, os.path.relpath(evt.path, rt), evt.action)
                        watcher = IOCPFileWatcher(
                            directory=abs_root,
                            recursive=True,
                            debounce_ms=self.debounce_window_s * 1000.0,
                            callback=make_cb(abs_root),
                        )
                        watcher.start()
                        self._iocp_watchers[abs_root] = watcher
                self._backend = "iocp_native"

            self._running = True
            return True

    def stop(self) -> None:
        """Stop all observers and cancel any pending debounce timers."""
        with self._lock:
            if not self._running:
                return
            if self._observer:
                try:
                    self._observer.stop()
                    self._observer.join(timeout=2.0)
                except Exception:
                    pass
                self._observer = None

            for watcher in self._iocp_watchers.values():
                try:
                    watcher.stop()
                except Exception:
                    pass
            self._iocp_watchers.clear()

            for handler in self._handlers.values():
                handler.cancel_all()
            self._handlers.clear()
            self._running = False

    def stats(self) -> WatcherStats:
        """Inspect current daemon metrics."""
        with self._lock:
            total_rx = sum(h.events_received for h in self._handlers.values())
            total_debounced = sum(h.events_debounced for h in self._handlers.values())
            total_dispatched = sum(h.callbacks_dispatched for h in self._handlers.values())
            roots = list(self._handlers.keys()) or list(self._iocp_watchers.keys())
            return WatcherStats(
                running=self._running,
                watched_roots=tuple(roots),
                events_received=total_rx,
                events_debounced=total_debounced,
                callbacks_dispatched=total_dispatched,
                watchdog_backend=self._backend,
            )
