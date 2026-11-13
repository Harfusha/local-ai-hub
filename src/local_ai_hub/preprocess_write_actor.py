from __future__ import annotations

import concurrent.futures
import logging
from pathlib import Path
import queue
import sqlite3
import threading
from typing import Any, Callable

from .sqlite_support import connect_sqlite, write_transaction

logger = logging.getLogger(__name__)

_SENTINEL = object()


class _BatchOperationFailed(Exception):
    """Signal that an atomic batch must roll back before isolated retries."""


class PreprocessWriteActor:
    """Dedicated single-writer SQLite actor with batching queue.

    Eliminates multi-threaded database lock contention and busy-retry storms
    by serializing write transactions onto a single worker thread while allowing
    CPU phases to dispatch writes asynchronously or await batch completion.
    """

    def __init__(
        self,
        db_path: Path | str,
        *,
        max_batch_size: int = 64,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.db_path = Path(db_path)
        self.max_batch_size = max(1, max_batch_size)
        self.timeout_seconds = timeout_seconds
        self._queue: queue.Queue[Any] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(
                target=self._worker,
                name=f"sqlite-writer-{self.db_path.stem}",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._queue.put(_SENTINEL)
            thread = self._thread

        if thread and thread.is_alive():
            thread.join(timeout=timeout)

    @property
    def is_alive(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    def is_current_thread(self) -> bool:
        return self._thread is not None and threading.current_thread() is self._thread

    def submit(
        self,
        operation: Callable[[sqlite3.Connection], Any],
        *,
        timeout: float | None = None,
    ) -> Any:
        """Submit a write operation to the actor and return its result."""
        if not self.is_alive or self.is_current_thread():
            # Fallback: execute synchronously directly on connection
            con = connect_sqlite(
                self.db_path,
                timeout_seconds=self.timeout_seconds,
                row_factory=sqlite3.Row,
            )
            try:
                with write_transaction(con, max_duration_seconds=5.0, rollback_label="preprocess write actor"):
                    return operation(con)
            finally:
                con.close()

        fut: concurrent.futures.Future[Any] = concurrent.futures.Future()
        self._queue.put((operation, fut))
        wait_time = timeout if timeout is not None else self.timeout_seconds
        return fut.result(timeout=wait_time)

    def _worker(self) -> None:
        con: sqlite3.Connection | None = None
        try:
            con = connect_sqlite(
                self.db_path,
                timeout_seconds=self.timeout_seconds,
                row_factory=sqlite3.Row,
            )
            try:
                con.execute("PRAGMA cache_size=-65536")
                con.execute("PRAGMA mmap_size=536870912")
                con.execute("PRAGMA synchronous=NORMAL")
                con.execute("PRAGMA temp_store=MEMORY")
                con.execute("PRAGMA journal_size_limit=67108864")
            except sqlite3.OperationalError:
                pass

            while True:
                item = self._queue.get()
                if item is _SENTINEL:
                    self._queue.task_done()
                    break

                batch = [item]
                while len(batch) < self.max_batch_size:
                    try:
                        next_item = self._queue.get_nowait()
                        if next_item is _SENTINEL:
                            self._queue.put(_SENTINEL)
                            break
                        batch.append(next_item)
                    except queue.Empty:
                        break

                if len(batch) == 1:
                    op, fut = batch[0]
                    if fut.set_running_or_notify_cancel():
                        try:
                            with write_transaction(con, max_duration_seconds=5.0, rollback_label="preprocess write actor"):
                                res = op(con)
                            fut.set_result(res)
                        except Exception as exc:
                            fut.set_exception(exc)
                    self._queue.task_done()
                    continue

                # Multi-item batch with isolated fallback on individual failure
                results: list[tuple[concurrent.futures.Future[Any], Any]] = []
                try:
                    with write_transaction(con, max_duration_seconds=5.0, rollback_label="preprocess write actor batch"):
                        for op, fut in batch:
                            if not fut.set_running_or_notify_cancel():
                                continue
                            try:
                                res = op(con)
                                results.append((fut, res))
                            except Exception as op_exc:
                                raise _BatchOperationFailed from op_exc
                    for fut, res in results:
                        fut.set_result(res)
                except _BatchOperationFailed:
                    # The shared transaction has rolled back; replay each operation
                    # independently so one bad write does not discard good neighbors.
                    for op, fut in batch:
                        if fut.done():
                            continue
                        try:
                            with write_transaction(con, max_duration_seconds=5.0, rollback_label="preprocess write actor retry"):
                                res = op(con)
                            fut.set_result(res)
                        except Exception as indiv_exc:
                            fut.set_exception(indiv_exc)
                except Exception as tx_exc:
                    for _, fut in batch:
                        if not fut.done():
                            fut.set_exception(tx_exc)
                finally:
                    for _ in batch:
                        self._queue.task_done()

        except Exception as exc:
            logger.error("PreprocessWriteActor fatal error on %s: %s", self.db_path, exc)
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass
