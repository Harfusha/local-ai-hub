from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.memory import WorkspaceMemoryStore


def test_workspace_memos_are_root_scoped_and_have_no_owner_partition(tmp_path: Path) -> None:
    store = WorkspaceMemoryStore(tmp_path / "state")
    root_a = str(tmp_path / "repo-a")
    root_b = str(tmp_path / "repo-b")

    written = store.put(root_a, "decision", "keep the workspace identity")
    found = store.get(root_a, "decision")

    assert written["success"] is True
    assert found["value"] == "keep the workspace identity"
    assert "tenant" not in written
    assert "tenant" not in found
    assert store.get(root_b, "decision")["success"] is False
    with closing(sqlite3.connect(store.path)) as con, con:
        columns = {str(row[1]) for row in con.execute("PRAGMA table_info(memos)")}
    assert "tenant" not in columns
    assert {"workspace", "memo_key", "value", "metadata", "version"} <= columns


def test_retired_tenant_field_is_rejected_in_memo_metadata(tmp_path: Path) -> None:
    store = WorkspaceMemoryStore(tmp_path / "state")

    with pytest.raises(ValueError, match="tenant"):
        store.put("repo", "memo", "value", metadata={"tenant": None})
    with pytest.raises(TypeError):
        store.put("repo", "memo", "value", tenant="")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        store.delete("repo", "memo", tenant=False)  # type: ignore[call-arg]


def test_tenant_shaped_memo_database_is_refused_without_rewriting(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    db_path = state_dir / "workspace_memory.sqlite3"
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute(
            "CREATE TABLE memos (workspace TEXT NOT NULL, memo_key TEXT NOT NULL, "
            "value TEXT NOT NULL, tenant TEXT NOT NULL, metadata TEXT NOT NULL, "
            "updated_at REAL NOT NULL, expires_at REAL NOT NULL, version INTEGER NOT NULL, "
            "PRIMARY KEY(workspace,memo_key))"
        )
        con.execute(
            "CREATE TABLE memo_versions (workspace TEXT NOT NULL, memo_key TEXT NOT NULL, "
            "version INTEGER NOT NULL, PRIMARY KEY(workspace,memo_key))"
        )
        con.execute(
            "INSERT INTO memos VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("repo", "keep", "durable value", "owner-a", "{}", 1.0, 9999999999.0, 1),
        )
        con.execute("INSERT INTO memo_versions VALUES (?, ?, ?)", ("repo", "keep", 1))

    original = db_path.read_bytes()
    with pytest.raises(RuntimeError, match="offline conversion"):
        WorkspaceMemoryStore(state_dir)

    assert db_path.read_bytes() == original
