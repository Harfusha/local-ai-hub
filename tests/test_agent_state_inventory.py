from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from local_ai_hub.agent_state_inventory import inspect_agent_state_inventory


def test_inventory_rejects_missing_or_symlinked_db(tmp_path: Path):
    res = inspect_agent_state_inventory(tmp_path)
    assert not res["success"]
    assert res["reason"] == "database_unavailable"


def test_inventory_rejects_sidecars_present(tmp_path: Path):
    db = tmp_path / "agent_state.sqlite"
    db.write_bytes(b"SQLite format 3\x00")
    wal = tmp_path / "agent_state.sqlite-wal"
    wal.write_bytes(b"wal content")
    res = inspect_agent_state_inventory(tmp_path)
    assert not res["success"]
    assert res["reason"] == "offline_snapshot_required"


def test_inventory_classifies_tables(tmp_path: Path):
    db = tmp_path / "agent_state.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE agent_tasks_projection (task_id TEXT, status TEXT, contract TEXT, checkpoint TEXT, context TEXT, owner TEXT, created_at REAL, updated_at REAL, lease_id TEXT, receipts TEXT, heartbeat_expires_at REAL)")
        con.commit()
    res = inspect_agent_state_inventory(tmp_path)
    assert res["success"]
    assert res["complete"]
    assert any(t["table"] == "agent_tasks_projection" and t["state"] == "classified" for t in res["tables"])
