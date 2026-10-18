from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.swarm import SwarmCoordinator


class _RecordingLeases:
    def __init__(self) -> None:
        self.claims: list[dict[str, object]] = []
        self.releases: list[str] = []

    def list(self, *, root: str) -> list[dict[str, object]]:
        return []

    def claim(self, **kwargs: object) -> dict[str, object]:
        self.claims.append(kwargs)
        return {"success": True}

    def release_owner(self, *, owner: str) -> dict[str, object]:
        self.releases.append(owner)
        return {"success": True}


def test_swarm_schema_and_lease_owner_are_execution_scoped(tmp_path: Path) -> None:
    db_path = tmp_path / "swarm.sqlite"
    leases = _RecordingLeases()
    coordinator = SwarmCoordinator(db_path, leases=leases)  # type: ignore[arg-type]

    result = coordinator.dispatch(
        "edit a file", target_paths=["src/example.py"], root=str(tmp_path)
    )

    assert result["success"] is True
    assert leases.claims[0]["owner"] == f"swarm:{result['swarm_id']}"
    assert leases.claims[0]["root"] == str(tmp_path)
    with closing(sqlite3.connect(db_path)) as con, con:
        columns = {str(row[1]) for row in con.execute("PRAGMA table_info(agent_swarms)")}
    assert "tenant" not in columns
    assert "tenant_identity" not in columns
    assert {"swarm_id", "root", "author"} <= columns


def test_tenant_shaped_swarm_schema_is_refused_without_rewriting(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite"
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute(
            "CREATE TABLE agent_swarms ("
            "swarm_id TEXT PRIMARY KEY, tenant TEXT, goal TEXT NOT NULL, "
            "target_paths TEXT NOT NULL, test_command TEXT NOT NULL, "
            "author TEXT NOT NULL, root TEXT NOT NULL, state TEXT NOT NULL, "
            "receipt_id TEXT, history TEXT NOT NULL, created_at REAL NOT NULL, "
            "updated_at REAL NOT NULL, version INTEGER NOT NULL)"
        )
        con.execute(
            "INSERT INTO agent_swarms VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("swarm_legacy", "owner-a", "goal", "[]", "", "author", str(tmp_path),
             "PENDING", None, "[]", 1.0, 1.0, 1),
        )

    original = db_path.read_bytes()
    with pytest.raises((RuntimeError, sqlite3.DatabaseError)):
        SwarmCoordinator(db_path)

    assert db_path.read_bytes() == original
