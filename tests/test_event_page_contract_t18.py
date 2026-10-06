from __future__ import annotations

import sqlite3
import time
from contextlib import closing

from local_ai_hub.agent_events import AgentEvent, AgentStateStore


def _store_with_events(tmp_path, stream_id: str, count: int, *, created_at: float | None = None) -> AgentStateStore:
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    for seq in range(1, count + 1):
        event = AgentEvent.create(
            stream_id,
            "task.progress",
            {"step": seq},
            idempotency_key=f"{stream_id}-{seq}",
            created_at=created_at + seq if created_at is not None else None,
        )
        assert store.append(event).seq == seq
    return store


def _seed_durable_cursor(
    store: AgentStateStore,
    stream_id: str,
    *,
    last_seq: int,
    first_retained_seq: int,
) -> None:
    store._ensure_schema()
    con = sqlite3.connect(store.db_path)
    try:
        con.execute(
            """CREATE TABLE IF NOT EXISTS agent_event_cursors (
                   stream_id TEXT PRIMARY KEY,
                   last_seq INTEGER NOT NULL,
                   first_retained_seq INTEGER NOT NULL
               )"""
        )
        con.execute(
            """INSERT OR REPLACE INTO agent_event_cursors
               (stream_id, last_seq, first_retained_seq) VALUES (?, ?, ?)""",
            (stream_id, last_seq, first_retained_seq),
        )
        con.commit()
    finally:
        con.close()


def _delete_sequences(store: AgentStateStore, stream_id: str, *sequences: int) -> None:
    with closing(sqlite3.connect(store.db_path)) as con:
        with con:
            con.executemany(
                "DELETE FROM agent_events WHERE stream_id=? AND seq=?",
                [(stream_id, seq) for seq in sequences],
            )


def test_future_cursor_replays_first_retained_event_after_reset(tmp_path):
    stream_id = "task:future-cursor"
    store = _store_with_events(tmp_path, stream_id, 3)
    _seed_durable_cursor(store, stream_id, last_seq=3, first_retained_seq=3)
    _delete_sequences(store, stream_id, 1, 2)

    page = store.event_page(stream_id, after_seq=99, limit=10)

    assert page["success"] is True
    assert [event["seq"] for event in page["events"]] == [3]
    assert page["events"][0]["stream_id"] == stream_id
    assert page["events"][0]["kind"] == "task.progress"
    assert page["events"][0]["payload"] == {"step": 3}
    assert page["next_seq"] == 3
    assert page["first_retained_seq"] == 3
    assert page["last_seq"] == 3
    assert page["gap_ranges"] == []
    assert page["cursor_reset"] is True


def test_full_prune_without_snapshot_preserves_durable_high_water(tmp_path):
    stream_id = "task:pruned-no-snapshot"
    expired_at = time.time() - 60 * 86400
    store = _store_with_events(tmp_path, stream_id, 3, created_at=expired_at)
    _seed_durable_cursor(store, stream_id, last_seq=3, first_retained_seq=1)

    assert store.cleanup(retention_days=30)["deleted_events"] == 3
    assert store.latest_snapshot(stream_id) is None

    page = store.event_page(stream_id, after_seq=0, limit=10)

    assert page["events"] == []
    assert page["first_retained_seq"] is None
    assert page["last_seq"] == 3
    assert page["gap_ranges"] == [{"from_seq": 1, "to_seq": 3}]
    assert page["next_seq"] == 3
    assert page["cursor_reset"] is False


def test_next_seq_advances_through_trailing_gap_after_visible_events(tmp_path):
    stream_id = "task:trailing-gap"
    store = _store_with_events(tmp_path, stream_id, 4)
    _seed_durable_cursor(store, stream_id, last_seq=4, first_retained_seq=1)
    _delete_sequences(store, stream_id, 2, 4)

    page = store.event_page(stream_id, after_seq=0, limit=10)

    assert [event["seq"] for event in page["events"]] == [1, 3]
    assert page["gap_ranges"] == [
        {"from_seq": 2, "to_seq": 2},
        {"from_seq": 4, "to_seq": 4},
    ]
    assert page["last_seq"] == 4
    assert page["next_seq"] == 4
    assert page["has_more"] is False
