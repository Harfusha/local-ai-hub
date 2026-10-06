from __future__ import annotations

import sqlite3
from dataclasses import replace
import json
from contextlib import closing

import pytest

from local_ai_hub import agent_memory as agent_memory_module
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStore
from local_ai_hub.sqlite_support import connect_sqlite


def test_record_update_fts_write_failure_rolls_back_durable_record_and_preserves_events(tmp_path, monkeypatch):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store = MemoryStore(state_store)
    original = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.TASK,
            scope_id="fts-atomicity",
            key="answer",
            value="before",
        ),
        actor="user",
        idempotency_key="before-update",
    )
    with closing(connect_sqlite(state_store.db_path)) as con:
        stream_id = con.execute(
            "SELECT stream_id FROM agent_events WHERE idempotency_key = ?",
            ("before-update",),
        ).fetchone()[0]
    events_before = state_store.events(stream_id)
    updated = replace(original, value="after")
    real_connect = agent_memory_module.connect_sqlite

    def connect_with_fts_write_fault(*args, **kwargs):
        con = real_connect(*args, **kwargs)

        def deny_fts_insert(action, table, _column, _database, _trigger):
            if action == sqlite3.SQLITE_INSERT and table == "agent_memory_fts":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        con.set_authorizer(deny_fts_insert)
        return con

    monkeypatch.setattr(agent_memory_module, "connect_sqlite", connect_with_fts_write_fault)
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        store.record(updated, actor="user", idempotency_key="failed-update")
    con = connect_sqlite(state_store.db_path)
    try:
        row = con.execute(
            "SELECT value FROM agent_memory_records WHERE record_id = ?",
            (original.record_id,),
        ).fetchone()
        fts = con.execute(
            "SELECT value FROM agent_memory_fts WHERE record_id = ?",
            (original.record_id,),
        ).fetchone()
        failed_event = con.execute(
            "SELECT COUNT(*) FROM agent_events WHERE idempotency_key = ?",
            ("failed-update",),
        ).fetchone()[0]
    finally:
        con.close()

    assert json.loads(row[0]) == "before"
    assert fts == ("before",)
    assert failed_event == 0
    assert state_store.events(stream_id) == events_before


def test_record_write_succeeds_when_optional_fts_table_is_absent(tmp_path):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store = MemoryStore(state_store)
    store._init_table()
    con = connect_sqlite(state_store.db_path, isolation_level=None)
    try:
        con.execute("DROP TABLE agent_memory_fts")
        con.execute("BEGIN IMMEDIATE")
        record = MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.TASK,
            scope_id="fts-optional",
            key="answer",
            value="durable without index",
        )
        store._save_record_row(con, record)
        con.execute("COMMIT")
        row = con.execute(
            "SELECT value FROM agent_memory_records WHERE record_id = ?",
            (record.record_id,),
        ).fetchone()
    except Exception:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        con.close()

    assert row == ('"durable without index"',)
