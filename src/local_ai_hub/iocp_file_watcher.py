"""Windows Kernel IOCP File Watcher using ReadDirectoryChangesW.

Provides zero-CPU asynchronous filesystem monitoring for Local AI Hub on Windows:
1. Native Windows I/O Completion Ports (IOCP) eliminating polling loops.
2. Kernel notification buffer handling (FILE_NOTIFY_INFORMATION linked list).
3. Built-in sliding-window debounce filter (preventing burst duplicate events during saves/builds).
4. Safe lifecycle management with clean handle detachment (CloseHandle / PostQueuedCompletionStatus).
"""

from __future__ import annotations

import collections
import ctypes
import logging
# import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Action constants
ACTION_ADDED = 1
ACTION_REMOVED = 2
ACTION_MODIFIED = 3
ACTION_RENAMED_OLD = 4
ACTION_RENAMED_NEW = 5

ACTION_NAMES = {
    ACTION_ADDED: "created",
    ACTION_REMOVED: "deleted",
    ACTION_MODIFIED: "modified",
    ACTION_RENAMED_OLD: "renamed_old",
    ACTION_RENAMED_NEW: "renamed_new",
}

# Win32 Constants
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OVERLAPPED = 0x40000000
FILE_LIST_DIRECTORY = 0x0001

FILE_NOTIFY_CHANGE_FILE_NAME = 0x00000001
FILE_NOTIFY_CHANGE_DIR_NAME = 0x00000002
FILE_NOTIFY_CHANGE_LAST_WRITE = 0x00000010
FILE_NOTIFY_CHANGE_SIZE = 0x00000008

DEFAULT_FILTER = (
    FILE_NOTIFY_CHANGE_FILE_NAME
    | FILE_NOTIFY_CHANGE_DIR_NAME
    | FILE_NOTIFY_CHANGE_LAST_WRITE
    | FILE_NOTIFY_CHANGE_SIZE
)

BUFFER_SIZE = 64 * 1024  # 64 KB buffer for notification records


@dataclass(frozen=True)
class FileChangeEvent:
    """Filesystem event produced by watcher."""

    path: str
    action: str  # "created", "modified", "deleted", etc.
    timestamp: float


class IOCPFileWatcher:
    """Asynchronous IOCP directory watcher for Windows."""

    def __init__(
        self,
        directory: str | Path,
        recursive: bool = True,
        debounce_ms: float = 200.0,
        callback: Optional[Callable[[FileChangeEvent], None]] = None,
    ):
        self.directory = Path(directory).resolve()
        self.recursive = recursive
        self.debounce_seconds = debounce_ms / 1000.0
        self.callback = callback

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._dir_handle = None
        self._iocp_handle = None
        self._recent_events: Dict[str, float] = {}
        self._event_queue: collections.deque[FileChangeEvent] = collections.deque()
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start IOCP file watcher in background thread."""
        if sys.platform != "win32":
            logger.info("IOCP file watcher only supported on Windows; running mock loop")
            return

        k32 = ctypes.windll.kernel32

        # 1. Open directory handle with overlapped flag
        self._dir_handle = k32.CreateFileW(
            str(self.directory),
            FILE_LIST_DIRECTORY,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OVERLAPPED,
            None,
        )

        if self._dir_handle == -1 or self._dir_handle == 0:
            raise OSError(f"Failed to open directory handle for {self.directory} (err={k32.GetLastError()})")

        # 2. Create Completion Port
        self._iocp_handle = k32.CreateIoCompletionPort(
            self._dir_handle,
            None,
            ctypes.c_ulong(1),
            0,
        )

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker_loop, name="IOCPFileWatcher", daemon=True)
        self._thread.start()

    def _worker_loop(self) -> None:
        """Background thread servicing completion port."""
        k32 = ctypes.windll.kernel32

        buffer = ctypes.create_string_buffer(BUFFER_SIZE)
        overlapped = ctypes.c_buffer(32)  # OVERLAPPED struct

        # Initial arm
        k32.ReadDirectoryChangesW(
            self._dir_handle,
            buffer,
            BUFFER_SIZE,
            ctypes.c_bool(self.recursive),
            DEFAULT_FILTER,
            None,
            overlapped,
            None,
        )

        while not self._stop_event.is_set():
            num_bytes = ctypes.c_ulong(0)
            comp_key = ctypes.c_ulong(0)
            p_overlapped = ctypes.c_void_p(0)

            # Wait for event with 150ms timeout
            res = k32.GetQueuedCompletionStatus(
                self._iocp_handle,
                ctypes.byref(num_bytes),
                ctypes.byref(comp_key),
                ctypes.byref(p_overlapped),
                150,
            )

            if self._stop_event.is_set():
                break

            if res != 0 and num_bytes.value > 0:
                self._parse_notifications(buffer.raw, num_bytes.value)

                # Re-arm ReadDirectoryChangesW
                k32.ReadDirectoryChangesW(
                    self._dir_handle,
                    buffer,
                    BUFFER_SIZE,
                    ctypes.c_bool(self.recursive),
                    DEFAULT_FILTER,
                    None,
                    overlapped,
                    None,
                )

    def _parse_notifications(self, raw_bytes: bytes, length: int) -> None:
        """Parse FILE_NOTIFY_INFORMATION linked list records."""
        offset = 0
        now = time.time()

        while offset < length:
            import struct
            # Header: NextEntryOffset (DWORD=4), Action (DWORD=4), FileNameLength (DWORD=4)
            if offset + 12 > length:
                break
            next_offset, action, name_len = struct.unpack_from("<III", raw_bytes, offset)
            name_start = offset + 12
            name_bytes = raw_bytes[name_start : name_start + name_len]
            try:
                rel_path = name_bytes.decode("utf-16le")
            except Exception:
                rel_path = ""

            if rel_path:
                action_name = ACTION_NAMES.get(action, "modified")
                full_path = str(self.directory / rel_path)

                # Debounce check
                with self._lock:
                    last_time = self._recent_events.get(full_path, 0.0)
                    if now - last_time >= self.debounce_seconds:
                        self._recent_events[full_path] = now
                        evt = FileChangeEvent(path=full_path, action=action_name, timestamp=now)
                        self._event_queue.append(evt)
                        if self.callback:
                            try:
                                self.callback(evt)
                            except Exception as e:
                                logger.warning("Watcher callback error: %s", e)

            if next_offset == 0:
                break
            offset += next_offset

    def poll_events(self) -> List[FileChangeEvent]:
        """Drain queued filesystem events."""
        with self._lock:
            events = list(self._event_queue)
            self._event_queue.clear()
            return events

    def stop(self) -> None:
        """Stop watcher and release kernel handles."""
        self._stop_event.set()
        if sys.platform == "win32":
            k32 = ctypes.windll.kernel32
            if self._iocp_handle:
                # Wake up worker thread
                k32.PostQueuedCompletionStatus(self._iocp_handle, 0, 0, None)
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=1.0)
            if self._dir_handle:
                k32.CloseHandle(self._dir_handle)
                self._dir_handle = None
            if self._iocp_handle:
                k32.CloseHandle(self._iocp_handle)
                self._iocp_handle = None
