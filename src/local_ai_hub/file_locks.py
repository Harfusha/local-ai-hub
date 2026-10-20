"""Bounded thread/process serialization for atomic local file updates."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import threading
import time
from typing import Iterator


_LOCKS = tuple(threading.RLock() for _ in range(64))


@contextmanager
def exclusive_file_update(path: Path, *, timeout: float = 5.0) -> Iterator[None]:
    """Keep a stable lock file: unlinking it could split concurrent owners."""
    deadline = time.monotonic() + timeout
    guard = _LOCKS[hash(os.path.normcase(str(path.resolve()))) % len(_LOCKS)]
    if not guard.acquire(timeout=max(0.0, timeout)):
        raise TimeoutError("file update lock timed out")
    descriptor = None
    acquired = False
    try:
        lock_path = path.with_name(path.name + ".lock")
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
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
        yield
    finally:
        try:
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
