"""Bounded thread/process serialization for atomic local file updates."""
from __future__ import annotations

from contextlib import contextmanager
import os
import stat
from pathlib import Path
import threading
import time
from typing import Iterator


_LOCKS = tuple(threading.RLock() for _ in range(64))
_HELD = threading.local()


def _open_lock_file(path: Path) -> int:
    if os.name == "nt":
        import ctypes
        import msvcrt
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                           wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        close = kernel.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        get_info = kernel.GetFileInformationByHandleEx
        get_info.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        get_info.restype = wintypes.BOOL
        get_type = kernel.GetFileType
        get_type.argtypes = [wintypes.HANDLE]
        get_type.restype = wintypes.DWORD

        class AttributeTag(ctypes.Structure):
            _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]

        # Do not follow the last reparse point or allow the open lock to be renamed.
        handle = create(str(path), 0x80000000 | 0x40000000, 0x1 | 0x2, None, 4,
                        0x00200000 | 0x80, None)
        if handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            info = AttributeTag()
            if not get_info(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            if info.attributes & (0x400 | 0x10) or get_type(handle) != 1:
                raise ValueError("lock file must be a regular file, not a reparse point")
            descriptor = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
        except BaseException:
            close(handle)
            raise
    else:
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("lock file must be a regular file with exactly one link")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


@contextmanager
def exclusive_file_update(path: Path, *, timeout: float = 5.0, reentrant: bool = False) -> Iterator[None]:
    """Keep a stable lock file: unlinking it could split concurrent owners."""
    deadline = time.monotonic() + timeout
    key = (os.getpid(), os.path.normcase(str(path.resolve())))
    guard = _LOCKS[hash(key[1]) % len(_LOCKS)]
    if not guard.acquire(timeout=max(0.0, timeout)):
        raise TimeoutError("file update lock timed out")
    descriptor = None
    acquired = False
    registered = False
    try:
        held = getattr(_HELD, "paths", None)
        if held is None:
            held = _HELD.paths = set()
        if reentrant and key in held:
            yield
            return
        lock_path = path.with_name(path.name + ".lock")
        descriptor = _open_lock_file(lock_path)
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("file update lock timed out") from None
                time.sleep(min(0.02, remaining))
        if reentrant:
            held.add(key)
            registered = True
        yield
    finally:
        try:
            if registered:
                held.remove(key)
            if descriptor is not None:
                try:
                    if acquired:
                        if os.name == "nt":
                            import msvcrt
                            os.lseek(descriptor, 0, os.SEEK_SET)
                            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)
        finally:
            guard.release()
