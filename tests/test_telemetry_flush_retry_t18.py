from __future__ import annotations

import sqlite3
import threading
from contextlib import closing

from local_ai_hub.telemetry import TelemetryStore


def test_busy_retry_flushes_held_batch_within_one_second(tmp_path, monkeypatch):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.5)
    original_flush_batch = store._flush_batch
    original_queue_get = store._queue.get
    attempts = 0
    operations: list[str] = []
    operations_lock = threading.Lock()

    def fail_once(batch):
        nonlocal attempts
        attempts += 1
        with operations_lock:
            operations.append("flush")
        if attempts == 1:
            raise sqlite3.OperationalError("database is locked")
        return original_flush_batch(batch)

    def observe_blocking_get(block=True, timeout=None):
        if block:
            with operations_lock:
                operations.append("get")
        return original_queue_get(block=block, timeout=timeout)

    monkeypatch.setattr(store, "_flush_batch", fail_once)
    monkeypatch.setattr(store._queue, "get", observe_blocking_get)
    try:
        store.record_error("provider", "generate", RuntimeError("synthetic busy retry"))

        assert store.flush(10)
        assert attempts >= 2
        with operations_lock:
            first_flush = operations.index("flush")
            second_flush = operations.index("flush", first_flush + 1)
            assert "get" not in operations[first_flush + 1:second_flush]
        with closing(store._connect()) as con:
            assert con.execute("SELECT COUNT(*) FROM errors").fetchone()[0] == 1
    finally:
        store.close()
