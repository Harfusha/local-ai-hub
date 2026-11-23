from __future__ import annotations

import concurrent.futures
import logging
from itertools import count
from pathlib import Path
import queue
import sqlite3
import threading
from typing import Any, Callable

from .sqlite_support import connect_sqlite, write_transaction

logger = logging.getLogger(__name__)

_SENTINEL = object()


class _BatchOperationFailed(Exception):
    """Signal that a failed callback must roll back the batch transaction."""


class WriteOutcomeUnknown(TimeoutError):
    """A running write exceeded its wait deadline and may still commit."""


class WriteQueueTimeout(TimeoutError):
    """A queued write was cancelled before the worker began it."""


class BatchRolledBackError(RuntimeError):
    """A failed batch rolled back SQLite work but may have callback side effects."""


def _set_write_failure(future: concurrent.futures.Future[Any], error: Exception) -> None:
    if future.done():
        return
    try:
        future.set_exception(error)
    except concurrent.futures.InvalidStateError:
        # The caller can cancel a queued write while its failure is published.
        if not future.cancelled():
            raise


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
        connection_timeout_seconds: float | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.max_batch_size = max(1, max_batch_size)
        self.timeout_seconds = timeout_seconds
        self.connection_timeout_seconds = (
            timeout_seconds if connection_timeout_seconds is None else connection_timeout_seconds
        )
        self._queue: queue.PriorityQueue[tuple[int, int, Any]] = queue.PriorityQueue()
        self._sequence = count()
        self._thread: threading.Thread | None = None
        self._worker_connection: sqlite3.Connection | None = None
        self._running = False
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                if self._running:
                    return
                raise RuntimeError("write actor is stopping")
            self._running = True
            self._thread = threading.Thread(
                target=self._worker,
                name=f"sqlite-writer-{self.db_path.stem}",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            thread = self._thread
            if self._running:
                self._running = False
                self._queue.put((2, next(self._sequence), _SENTINEL))

        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=timeout)

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def is_current_thread(self) -> bool:
        return self._thread is not None and threading.current_thread() is self._thread

    def submit(
        self,
        operation: Callable[[sqlite3.Connection], Any],
        *,
        timeout: float | None = None,
        priority: int = 1,
    ) -> Any:
        """Submit a write operation to the actor and return its result."""
        if type(priority) is not int or priority not in {0, 1}:
            raise ValueError("write actor priority must be 0 (project state) or 1 (background)")
        if self.is_current_thread():
            return self._submit_inline(operation)

        fut: concurrent.futures.Future[Any] = concurrent.futures.Future()
        with self._lock:
            thread = self._thread
            if thread is not None and thread.is_alive():
                if not self._running:
                    raise RuntimeError("write actor is stopping")
                self._queue.put((priority, next(self._sequence), (operation, fut)))
            else:
                thread = None
        if thread is None:
            # No worker can race this fallback; the actor was never started or has exited.
            con = connect_sqlite(
                self.db_path,
                timeout_seconds=self.connection_timeout_seconds,
                row_factory=sqlite3.Row,
            )
            try:
                with write_transaction(con, max_duration_seconds=5.0, rollback_label="preprocess write actor"):
                    return operation(con)
            finally:
                con.close()
        wait_time = timeout if timeout is not None else self.timeout_seconds
        try:
            return fut.result(timeout=wait_time)
        except concurrent.futures.TimeoutError as exc:
            if fut.cancel():
                raise WriteQueueTimeout("write did not start before its queue deadline") from exc
            if fut.done():
                return fut.result()
            raise WriteOutcomeUnknown("write is still running; its commit outcome is unknown") from exc

    def _submit_inline(self, operation: Callable[[sqlite3.Connection], Any]) -> Any:
        con = self._worker_connection
        if con is None:
            raise RuntimeError("write actor does not own a SQLite connection")
        if not con.in_transaction:
            with write_transaction(con, max_duration_seconds=5.0, rollback_label="preprocess write actor"):
                return operation(con)

        con.execute("SAVEPOINT lah_preprocess_nested_write")
        try:
            result = operation(con)
        except BaseException:
            con.execute("ROLLBACK TO SAVEPOINT lah_preprocess_nested_write")
            con.execute("RELEASE SAVEPOINT lah_preprocess_nested_write")
            raise
        con.execute("RELEASE SAVEPOINT lah_preprocess_nested_write")
        return result

    def _worker(self) -> None:
        con: sqlite3.Connection | None = None
        try:
            con = connect_sqlite(
                self.db_path,
                timeout_seconds=self.connection_timeout_seconds,
                row_factory=sqlite3.Row,
            )
            self._worker_connection = con
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
                if item[2] is _SENTINEL:
                    self._queue.task_done()
                    break

                batch = [item[2]]
                while len(batch) < self.max_batch_size:
                    try:
                        next_item = self._queue.get_nowait()
                        if next_item[2] is _SENTINEL:
                            self._queue.task_done()
                            self._queue.put(next_item)
                            break
                        if next_item[0] != item[0]:
                            self._queue.task_done()
                            self._queue.put(next_item)
                            break
                        batch.append(next_item[2])
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
                except _BatchOperationFailed as batch_exc:
                    self._fail_batch(batch, batch_exc.__cause__ or batch_exc)
                except Exception as tx_exc:
                    self._fail_batch(batch, tx_exc)
                finally:
                    for _ in batch:
                        self._queue.task_done()

        except Exception as exc:
            logger.error("PreprocessWriteActor fatal error on %s: %s", self.db_path, exc)
        finally:
            self._worker_connection = None
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass
            with self._lock:
                self._running = False
            self._fail_queued()

    @staticmethod
    def _fail_batch(
        batch: list[tuple[Callable[[sqlite3.Connection], Any], concurrent.futures.Future[Any]]],
        cause: BaseException,
    ) -> None:
        message = f"write batch was rolled back; callback side effects may remain: {cause}"
        for _, fut in batch:
            _set_write_failure(fut, BatchRolledBackError(message))

    def _fail_queued(self) -> None:
        while True:
            try:
                _, _, item = self._queue.get_nowait()
            except queue.Empty:
                return
            try:
                if item is not _SENTINEL:
                    _, fut = item
                    _set_write_failure(fut, RuntimeError("write actor worker stopped before processing the queued write"))
            finally:
                self._queue.task_done()
