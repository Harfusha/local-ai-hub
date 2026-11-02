"""Experimental single-instance Windows message pipe; not a launcher service."""
from __future__ import annotations

import math
import os
import threading
import time
import uuid

from .opencode_pipe_identity import _valid_sid, matches_pipe_client


def _deadline(timeout: float) -> float:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise ValueError("invalid pipe timeout")
    return time.monotonic() + timeout


class _WindowsAPI:
    def __init__(self):
        if os.name != "nt":
            raise OSError("Windows named pipes are unavailable")
        import ctypes
        from ctypes import wintypes
        self.ctypes, self.types = ctypes, wintypes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.DWORD)]
        self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
        self.kernel.CreateNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
        self.kernel.CreateNamedPipeW.restype = wintypes.HANDLE
        self.kernel.ConnectNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
        self.kernel.ConnectNamedPipe.restype = wintypes.BOOL
        self.kernel.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        self.kernel.ReadFile.restype = wintypes.BOOL
        self.kernel.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        self.kernel.WriteFile.restype = wintypes.BOOL
        self.kernel.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.LocalFree.argtypes = [wintypes.LPVOID]


class WindowsPipe:
    def __init__(self, api: _WindowsAPI, handle: int, expected_sid: str, *, lock=None, release=None):
        self._api, self._handle, self._sid = api, handle, expected_sid
        self._lock = lock or threading.RLock()
        self._release = release
        self._closed = threading.Event()

    def read(self, limit: int, timeout: float) -> bytes | None:
        if type(limit) is not int or not 1 <= limit <= 65536:
            raise ValueError("invalid pipe read limit")
        deadline = _deadline(timeout)
        api = self._api
        while not self._closed.is_set():
            data = api.ctypes.create_string_buffer(limit)
            count = api.types.DWORD()
            with self._lock:
                if self._closed.is_set():
                    return None
                ok = api.kernel.ReadFile(self._handle, data, limit, api.ctypes.byref(count), None)
                error = api.ctypes.get_last_error() if not ok else 0
            if ok or error == 234:  # ERROR_MORE_DATA: partial message
                return data.raw[:count.value] if count.value else b""
            if error in (109, 233):  # broken or disconnected
                return None
            if error != 232:  # ERROR_NO_DATA is the nonblocking empty state
                raise OSError(error, "named-pipe read failed")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return b""
            self._closed.wait(min(remaining, 0.01))
        return None

    def matches_identity(self) -> bool:
        with self._lock:
            if self._closed.is_set():
                return False
            return matches_pipe_client(self._handle, self._sid)

    def write(self, data: bytes, timeout: float) -> None:
        if not isinstance(data, bytes):
            raise ValueError("pipe output must be bytes")
        deadline = _deadline(timeout)
        api = self._api
        offset = 0
        while offset < len(data):
            if self._closed.is_set():
                raise OSError("named pipe is closed")
            block = data[offset:offset + 16384]
            count = api.types.DWORD()
            with self._lock:
                if self._closed.is_set():
                    raise OSError("named pipe is closed")
                ok = api.kernel.WriteFile(self._handle, block, len(block), api.ctypes.byref(count), None)
                error = api.ctypes.get_last_error() if not ok else 0
            if ok and count.value:
                offset += count.value
                continue
            if not ok and error != 232:
                raise OSError(error, "named-pipe write failed")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("named-pipe write timed out")
            self._closed.wait(min(remaining, 0.01))

    def close(self) -> None:
        self._closed.set()
        with self._lock:
            if self._handle is not None:
                if self._release is not None:
                    self._release(self)
                else:
                    self._api.kernel.DisconnectNamedPipe(self._handle)
                    self._api.kernel.CloseHandle(self._handle)
                self._handle = None


class WindowsPipeListener:
    """Own one exclusive named pipe instance for sequential connections."""

    def __init__(self, expected_sid: str):
        if not _valid_sid(expected_sid):
            raise ValueError("invalid AppContainer SID")
        self._api = _WindowsAPI()
        self._sid = expected_sid
        self.name = "\\\\.\\pipe\\lah-opencode-" + uuid.uuid4().hex
        self._handle = None
        self._lock = threading.RLock()
        self._active = None

    def __enter__(self):
        api = self._api
        class SecurityAttributes(api.ctypes.Structure):
            _fields_ = [("length", api.types.DWORD), ("descriptor", api.types.LPVOID), ("inherit", api.types.BOOL)]
        descriptor = api.types.LPVOID()
        # Client access omits FILE_CREATE_PIPE_INSTANCE; ownership is separately
        # checked against the message token before any router dispatch.
        sddl = f"D:P(A;;GA;;;OW)(A;;GA;;;SY)(A;;0x0012019b;;;{self._sid})S:(ML;;NW;;;LW)"
        if not api.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, api.ctypes.byref(descriptor), None):
            raise OSError(api.ctypes.get_last_error(), "cannot create pipe security descriptor")
        try:
            attributes = SecurityAttributes(api.ctypes.sizeof(SecurityAttributes), descriptor, False)
            handle = api.kernel.CreateNamedPipeW(self.name, 3 | 0x00080000, 1 | 2 | 4 | 8, 1, 65536, 65536, 1000, api.ctypes.byref(attributes))
            if handle in (None, api.ctypes.c_void_p(-1).value):
                raise OSError(api.ctypes.get_last_error(), "cannot create named pipe")
            self._handle = handle
            return self
        finally:
            api.kernel.LocalFree(descriptor)

    def accept(self, *, timeout: float, stop: threading.Event | None = None) -> WindowsPipe:
        deadline = _deadline(timeout)
        stop = stop or threading.Event()
        while not stop.is_set():
            with self._lock:
                if self._handle is None or self._active is not None:
                    raise RuntimeError("pipe listener is not available")
                ok = self._api.kernel.ConnectNamedPipe(self._handle, None)
                error = self._api.ctypes.get_last_error() if not ok else 0
                if error == 535:  # ERROR_PIPE_CONNECTED
                    pipe = WindowsPipe(self._api, self._handle, self._sid, lock=self._lock, release=self._release_pipe)
                    self._active = pipe
                    return pipe
                if error == 232:  # Client disconnected before acceptance.
                    if not self._api.kernel.DisconnectNamedPipe(self._handle):
                        raise OSError(self._api.ctypes.get_last_error(), "cannot disconnect stale pipe client")
                    error = 536
                elif ok:
                    # In PIPE_NOWAIT mode success means the instance was made
                    # available, not that a client has connected.
                    error = 536
            if error != 536:  # ERROR_PIPE_LISTENING
                raise OSError(error, "named-pipe accept failed")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("named-pipe accept timed out")
            stop.wait(min(remaining, 0.01))
        raise InterruptedError("named-pipe accept cancelled")

    def _release_pipe(self, pipe):
        if pipe is not self._active or self._handle is None:
            raise RuntimeError("pipe ownership mismatch")
        if not self._api.kernel.DisconnectNamedPipe(self._handle):
            error = self._api.ctypes.get_last_error()
            self._api.kernel.CloseHandle(self._handle)
            self._handle = None
            self._active = None
            raise OSError(error, "cannot disconnect named pipe")
        self._active = None

    def __exit__(self, *_args):
        with self._lock:
            if self._active is not None:
                self._active.close()
            if self._handle is not None:
                self._api.kernel.CloseHandle(self._handle)
                self._handle = None
