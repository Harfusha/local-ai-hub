from __future__ import annotations

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import threading
import time
from typing import Iterator
import weakref

_CODE_INDEX_INIT_LOCKS: weakref.WeakValueDictionary[str, threading.RLock] = weakref.WeakValueDictionary()
_CODE_INDEX_INIT_LOCKS_GUARD = threading.Lock()
_CODE_INDEX_WRITE_LOCKS: weakref.WeakValueDictionary[str, threading.RLock] = weakref.WeakValueDictionary()
_CODE_INDEX_WRITE_LOCKS_GUARD = threading.Lock()


@contextmanager
def _code_index_initialization_lock(db_path: Path) -> Iterator[None]:
    """Serialize schema creation and corrupt-cache recovery across processes."""
    lock_path = db_path.with_name(db_path.name + ".init.lock")
    lock_key = os.path.normcase(str(lock_path.resolve()))
    with _CODE_INDEX_INIT_LOCKS_GUARD:
        thread_lock = _CODE_INDEX_INIT_LOCKS.get(lock_key)
        if thread_lock is None:
            thread_lock = threading.RLock()
            _CODE_INDEX_INIT_LOCKS[lock_key] = thread_lock

    with thread_lock:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as stream:
            deadline = time.monotonic() + 30.0
            locked = False
            if os.name == "nt":
                import msvcrt

                while not locked:
                    stream.seek(0)
                    try:
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                        locked = True
                    except OSError as exc:
                        if (
                            getattr(exc, "winerror", None) not in {33, 36}
                            and exc.errno not in {errno.EACCES, errno.EDEADLK, errno.EAGAIN}
                        ):
                            raise
                        if time.monotonic() >= deadline:
                            raise TimeoutError("timed out waiting for code-index initialization lock") from exc
                        time.sleep(0.05)
            else:
                import fcntl

                while not locked:
                    try:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        locked = True
                    except BlockingIOError as exc:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("timed out waiting for code-index initialization lock") from exc
                        time.sleep(0.05)

            try:
                stream.seek(0, os.SEEK_END)
                if stream.tell() == 0:
                    stream.write(b"\0")
                    stream.flush()
                yield
            finally:
                if os.name == "nt":
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _code_index_write_lock(db_path: Path) -> threading.RLock:
    """Share write-admission fencing across instances targeting the same SQLite file."""
    key = os.path.normcase(str(db_path.resolve()))
    with _CODE_INDEX_WRITE_LOCKS_GUARD:
        lock = _CODE_INDEX_WRITE_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _CODE_INDEX_WRITE_LOCKS[key] = lock
        return lock


_QUERY_CACHE_GENERATIONS: dict[str, int] = {}
_QUERY_CACHE_GENERATION_LOCK = threading.Lock()


def _query_cache_generation(database_key: str) -> int:
    with _QUERY_CACHE_GENERATION_LOCK:
        return _QUERY_CACHE_GENERATIONS.get(database_key, 0)


def _advance_query_cache_generation(database_key: str) -> None:
    with _QUERY_CACHE_GENERATION_LOCK:
        _QUERY_CACHE_GENERATIONS[database_key] = _QUERY_CACHE_GENERATIONS.get(database_key, 0) + 1
