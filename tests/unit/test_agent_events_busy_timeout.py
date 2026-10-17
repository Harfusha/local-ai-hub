from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import threading
import time

import local_ai_hub.agent_events as agent_events
from local_ai_hub.agent_events import AgentEvent, AgentStateStore


def test_append_uses_two_second_sqlite_busy_timeout(monkeypatch, tmp_path):
    db_path = tmp_path / "agent-events.sqlite3"
    store = AgentStateStore(db_path)
    store._ensure_schema()

    real_connect_sqlite = agent_events.connect_sqlite
    timeouts = []

    def recording_connect(*args, **kwargs):
        connection = real_connect_sqlite(*args, **kwargs)
        if Path(args[0]) == db_path:
            timeouts.append(connection.execute("PRAGMA busy_timeout").fetchone()[0])
        return connection

    monkeypatch.setattr(agent_events, "connect_sqlite", recording_connect)
    result = store.append(AgentEvent.create("stream", "test", {"value": 1}))

    assert result.error is None
    assert timeouts == [2000]


def test_concurrent_store_appends_are_durable_and_idempotent(tmp_path):
    db_path = tmp_path / "agent-events.sqlite3"
    stores = [AgentStateStore(db_path) for _ in range(6)]
    for store in stores:
        store._ensure_schema()
    blocker = sqlite3.connect(db_path, timeout=1, isolation_level=None, check_same_thread=False)
    blocker.execute("BEGIN IMMEDIATE")
    start_together = threading.Barrier(len(stores) + 1)

    events = [
        AgentEvent.create("stream", "test", {"index": index}, idempotency_key=f"key-{index}")
        for index in range(48)
    ]

    def append_one(index):
        if index < len(stores):
            start_together.wait(timeout=3)
        return stores[index % len(stores)].append(events[index])

    try:
        with ThreadPoolExecutor(max_workers=len(stores)) as pool:
            futures = [pool.submit(append_one, index) for index in range(len(events))]
            start_together.wait(timeout=3)
            time.sleep(0.1)
            blocker.execute("ROLLBACK")
            results = [future.result(timeout=5) for future in futures]
    finally:
        blocker.close()

    assert all(result.error is None and result.seq > 0 for result in results)
    assert sorted(result.seq for result in results) == list(range(1, len(events) + 1))

    duplicate = stores[0].append(events[0])
    assert duplicate.error is None
    assert duplicate.duplicate is True
    assert duplicate.seq == results[0].seq

    with closing(sqlite3.connect(db_path)) as connection:
        rows = connection.execute(
            "SELECT seq, idempotency_key FROM agent_events WHERE stream_id = ? ORDER BY seq",
            ("stream",),
        ).fetchall()
    assert len(rows) == len(events)
    assert [row[0] for row in rows] == list(range(1, len(events) + 1))
    assert len({row[1] for row in rows}) == len(events)
