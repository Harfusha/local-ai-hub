from __future__ import annotations

from contextlib import contextmanager
from concurrent.futures import Future
import queue
import sqlite3
import threading

from local_ai_hub import preprocess_write_actor as actor_module
from local_ai_hub.preprocess_write_actor import PreprocessWriteActor


class _GatedPriorityQueue(queue.PriorityQueue):
    def __init__(self) -> None:
        super().__init__()
        self.collecting = threading.Event()
        self.continue_collecting = threading.Event()

    def get_nowait(self):
        if not self.collecting.is_set():
            self.collecting.set()
            assert self.continue_collecting.wait(2)
        return super().get_nowait()


def test_priority_write_starts_a_separate_batch(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "preprocess.sqlite"
    con = sqlite3.connect(db_path)
    try:
        con.execute("CREATE TABLE writes (value TEXT NOT NULL)")
    finally:
        con.close()

    actor = PreprocessWriteActor(db_path, max_batch_size=8)
    gated_queue = _GatedPriorityQueue()
    actor._queue = gated_queue
    original_write_transaction = actor_module.write_transaction
    transaction_count = 0

    @contextmanager
    def track_transactions(con, **kwargs):
        nonlocal transaction_count
        transaction_count += 1
        with original_write_transaction(con, **kwargs):
            yield con

    monkeypatch.setattr(actor_module, "write_transaction", track_transactions)

    def enqueue(priority: int, value: str) -> Future[str]:
        future: Future[str] = Future()

        def operation(con):
            con.execute("INSERT INTO writes VALUES (?)", (value,))
            return value

        actor._queue.put((priority, next(actor._sequence), (operation, future)))
        return future

    low_first = enqueue(1, "low-first")
    actor.start()
    try:
        assert gated_queue.collecting.wait(2)
        low_second = enqueue(1, "low-second")
        priority = enqueue(0, "priority")
        gated_queue.continue_collecting.set()

        assert low_first.result(timeout=2) == "low-first"
        assert priority.result(timeout=2) == "priority"
        assert low_second.result(timeout=2) == "low-second"
        assert transaction_count == 3
    finally:
        gated_queue.continue_collecting.set()
        actor.stop()

