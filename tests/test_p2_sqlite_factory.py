from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

from local_ai_hub import diagnostics_export, laya_candidates, sqlite_support


def test_diagnostic_snapshot_uses_shared_factory_with_original_modes(tmp_path: Path, monkeypatch) -> None:
    source_path = tmp_path / "source.sqlite3"
    source = sqlite_support.connect_sqlite(source_path, foreign_keys=False)
    source.execute("CREATE TABLE sample (value INTEGER)")
    source.execute("INSERT INTO sample VALUES (7)")
    source.commit()
    source.close()

    calls: list[tuple[Path, dict[str, object]]] = []
    original = sqlite_support.connect_sqlite

    def tracked(path, **kwargs):
        calls.append((Path(path), kwargs))
        return original(path, **kwargs)

    monkeypatch.setattr(diagnostics_export, "connect_sqlite", tracked, raising=False)
    destination = tmp_path / "snapshot.sqlite3"
    diagnostics_export._snapshot_database(source_path, destination, cancelled=None)

    assert calls == [
        (source_path, {"timeout_seconds": 1.0, "read_only": True, "foreign_keys": False}),
        (
            destination,
            {"timeout_seconds": 5.0, "isolation_level": "DEFERRED", "foreign_keys": False},
        ),
    ]
    snapshot = sqlite_support.connect_sqlite(destination, read_only=True, foreign_keys=False)
    try:
        assert snapshot.execute("SELECT value FROM sample").fetchone()[0] == 7
    finally:
        snapshot.close()


def test_laya_candidate_store_uses_shared_factory_and_preserves_pragmas(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "agent_state.sqlite3"

    def ensure_schema() -> None:
        connection = sqlite_support.connect_sqlite(database, foreign_keys=False)
        connection.close()

    state_store = SimpleNamespace(enabled=True, db_path=database, _ensure_schema=ensure_schema)
    task_store = SimpleNamespace(state_store=state_store)
    calls: list[tuple[Path, dict[str, object]]] = []
    original = sqlite_support.connect_sqlite

    def tracked(path, **kwargs):
        calls.append((Path(path), kwargs))
        return original(path, **kwargs)

    monkeypatch.setattr(laya_candidates, "connect_sqlite", tracked, raising=False)
    connection = laya_candidates.LayaCandidateStore(tmp_path)._connect(task_store)
    try:
        assert calls == [
            (
                database,
                {
                    "timeout_seconds": 2.0,
                    "isolation_level": None,
                    "row_factory": sqlite3.Row,
                    "foreign_keys": True,
                    "wal": True,
                },
            )
        ]
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 2000
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA secure_delete").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        connection.close()
