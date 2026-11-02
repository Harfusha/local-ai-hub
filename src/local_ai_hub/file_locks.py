"""Bounded thread/process serialization for atomic local file updates."""
from __future__ import annotations

from contextlib import contextmanager
import errno
import logging
import os
import stat
from pathlib import Path
import threading
import time
from typing import Iterator


_LOCKS = tuple(threading.RLock() for _ in range(64))
_HELD = threading.local()
_LOGGER = logging.getLogger(__name__)


def _open_lock_file(path: Path, *, parent_fd: int | None = None) -> int:
    if os.name == "nt":
        if parent_fd is not None:
            raise ValueError("parent_fd is unavailable on Windows")
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
        descriptor = os.open(
            path.name if parent_fd is not None else path,
            os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_fd,
        )
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("lock file must be a regular file with exactly one link")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


@contextmanager
def exclusive_file_update(
    path: Path, *, timeout: float = 5.0, reentrant: bool = False, parent_fd: int | None = None
) -> Iterator[None]:
    """Keep a stable lock file: unlinking it could split concurrent owners."""
    deadline = time.monotonic() + timeout
    if parent_fd is None and os.name == "nt":
        identity = os.path.normcase(str(path.resolve()))
    else:
        directory = os.fstat(parent_fd) if parent_fd is not None else os.stat(path.parent)
        if not stat.S_ISDIR(directory.st_mode):
            raise ValueError("parent_fd must refer to a directory")
        identity = (directory.st_dev, directory.st_ino, path.name)
    key = (os.getpid(), identity)
    directory_key = (os.getpid(), directory.st_dev, directory.st_ino) if parent_fd is not None and os.name != "nt" else None
    guard = _LOCKS[hash(directory_key if directory_key is not None else key[1]) % len(_LOCKS)]
    if not guard.acquire(timeout=max(0.0, timeout)):
        raise TimeoutError("file update lock timed out")
    descriptor = None
    directory_descriptor = None
    directory_registered = False
    directory_fallback_registered = False
    acquired = False
    registered = False
    try:
        held = getattr(_HELD, "paths", None)
        if held is None:
            held = _HELD.paths = set()
        if reentrant and key in held:
            if (directory_key is not None
                    and directory_key not in getattr(_HELD, "directories", ())
                    and directory_key not in getattr(_HELD, "directory_fallbacks", ())):
                raise RuntimeError("cannot upgrade an existing file lock to a parent directory lock")
            yield
            return
        if directory_key is not None:
            # Serialize upgraded writers even if the lock filename is replaced.
            # The separate file lock below remains necessary for older writers;
            # neither lock prevents an uncooperative process moving the directory.
            held_directories = getattr(_HELD, "directories", None)
            if held_directories is None:
                held_directories = _HELD.directories = set()
            fallback_directories = getattr(_HELD, "directory_fallbacks", None)
            if fallback_directories is None:
                fallback_directories = _HELD.directory_fallbacks = set()
            if directory_key not in held_directories and directory_key not in fallback_directories:
                import fcntl
                directory_descriptor = os.open(".", os.O_RDONLY | os.O_DIRECTORY, dir_fd=parent_fd)
                while True:
                    try:
                        fcntl.flock(directory_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError as exc:
                        if exc.errno in (errno.EBADF, errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP):
                            os.close(directory_descriptor)
                            directory_descriptor = None
                            fallback_directories.add(directory_key)
                            directory_fallback_registered = True
                            _LOGGER.warning(
                                "Directory flock is unavailable; file lock remains active, "
                                "but replacing its name may split concurrent writers"
                            )
                            break
                        if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                            raise
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError("file update lock timed out") from None
                        time.sleep(min(0.02, remaining))
                if directory_descriptor is not None:
                    held_directories.add(directory_key)
                    directory_registered = True
        lock_path = path.with_name(path.name + ".lock")
        descriptor = (_open_lock_file(lock_path) if parent_fd is None
                      else _open_lock_file(lock_path, parent_fd=parent_fd))
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
            except OSError as exc:
                if os.name != "nt" and exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                    raise
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
            try:
                if directory_fallback_registered:
                    fallback_directories.remove(directory_key)
                if directory_descriptor is not None:
                    try:
                        if directory_registered:
                            held_directories.remove(directory_key)
                            fcntl.flock(directory_descriptor, fcntl.LOCK_UN)
                    finally:
                        os.close(directory_descriptor)
            finally:
                guard.release()
