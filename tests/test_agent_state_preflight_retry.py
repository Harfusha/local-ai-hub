import sqlite3
from contextlib import closing

from local_ai_hub.agent_events import AgentStateStore


def test_schema_preflight_retries_if_database_changes_during_snapshot(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    AgentStateStore(db_path)._ensure_schema()
    store = AgentStateStore(db_path)
    classify = AgentStateStore._classify_schema
    wrote = False

    def classify_with_concurrent_write(connection):
        nonlocal wrote
        result = classify(connection)
        if not wrote:
            wrote = True
            with closing(sqlite3.connect(db_path)) as writer:
                writer.execute(
                    "INSERT INTO agent_event_cursors(stream_id, last_seq, first_retained_seq) "
                    "VALUES (?, 0, 1)",
                    ("concurrent-preflight-writer",),
                )
                writer.commit()
        return result

    monkeypatch.setattr(store, "_classify_schema", classify_with_concurrent_write)

    store._ensure_schema()

    assert wrote
