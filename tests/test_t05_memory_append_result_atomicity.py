from contextlib import closing
from dataclasses import replace
import sqlite3

import pytest

from local_ai_hub.agent_events import AgentStateStore, AppendResult
from local_ai_hub.agent_memory import AgentScope, MemoryKind, MemoryRecord, MemoryStore


@pytest.mark.parametrize("replay", [False, True])
@pytest.mark.parametrize("append_before_error", [False, True])
def test_memory_append_result_error_rolls_back_projection(
    tmp_path, monkeypatch, replay, append_before_error,
):
    root = tmp_path / "repo"
    root.mkdir()
    state = AgentStateStore(tmp_path / "agent_state.sqlite3")
    memory = MemoryStore(state)
    record = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.REPOSITORY,
        scope_id=str(root),
        key="append-error",
        value="verified evidence",
        evidence_ids=("evidence-1",),
        provenance={"root": str(root), "tenant": "tenant-a"},
    )
    identity = {"scope": AgentScope.REPOSITORY, "root": str(root), "tenant": "tenant-a"}
    if replay:
        memory.record(record, idempotency_key="append-error-operation")
        # Exercise recovery from an event whose projection needs rebuilding.
        with closing(sqlite3.connect(state.db_path)) as con, con:
            con.execute("DELETE FROM agent_memory_records WHERE record_id = ?", (record.record_id,))
    else:
        memory._init_table()

    with closing(sqlite3.connect(state.db_path)) as con:
        original_events = con.execute("SELECT * FROM agent_events ORDER BY stream_id, seq").fetchall()
        original_cursors = con.execute("SELECT * FROM agent_event_cursors ORDER BY stream_id").fetchall()

    published = []
    monkeypatch.setattr(state, "_publish", published.append)
    original_append = state.append_in_transaction

    def reject_append(*args, **kwargs):
        if append_before_error:
            result = original_append(*args, **kwargs)
            return replace(result, event=None, error="append rejected")
        return AppendResult(seq=0, duplicate=False, error="append rejected")

    monkeypatch.setattr(state, "append_in_transaction", reject_append)
    error = None
    try:
        memory.record(record, idempotency_key="append-error-operation")
    except Exception as caught:
        error = caught

    # Verify durable atomicity even if the wrong exception masks the failure.
    with closing(sqlite3.connect(state.db_path)) as con:
        assert con.execute("SELECT COUNT(*) FROM agent_memory_records").fetchone()[0] == 0
        assert con.execute("SELECT * FROM agent_events ORDER BY stream_id, seq").fetchall() == original_events
        assert con.execute("SELECT * FROM agent_event_cursors ORDER BY stream_id").fetchall() == original_cursors
    assert memory.get(record.record_id, **identity) is None
    assert published == []
    assert isinstance(error, RuntimeError)
    assert str(error) == "append rejected"

    # Failed writes must not poison a valid retry or duplicate replay.
    monkeypatch.setattr(state, "append_in_transaction", original_append)
    saved = memory.record(record, idempotency_key="append-error-operation")
    assert memory.get(saved.record_id, **identity) == saved
    duplicate = memory.record(record, idempotency_key="append-error-operation")
    assert duplicate.record_id == saved.record_id
    with closing(sqlite3.connect(state.db_path)) as con:
        assert con.execute("SELECT COUNT(*) FROM agent_memory_records").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM agent_events WHERE kind = 'memory.recorded'").fetchone()[0] == 1
    assert all(event is not None for event in published)
    assert len([event for event in published if event.kind == "memory.recorded"]) == (0 if replay else 1)
