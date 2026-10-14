from __future__ import annotations

import sqlite3
from pathlib import Path

import local_ai_hub.deterministic as deterministic
from local_ai_hub.deterministic import DeterministicEngine


def test_migration_drift_detects_columns_missing_from_live_sqlite(tmp_path: Path) -> None:
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    migration = migration_dir / "001_users.sql"
    migration.write_text(
        "CREATE TABLE users (\n"
        "    id INTEGER PRIMARY KEY,\n"
        "    email TEXT NOT NULL,\n"
        "    username TEXT\n"
        ");\n",
        encoding="utf-8",
    )
    db_file = tmp_path / "app.db"
    with sqlite3.connect(db_file) as con:
        con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL)")

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
    result = engine.migration_drift(str(tmp_path), str(db_file))

    assert result["success"] is True
    assert result["schema_source"] == "sql_migrations"
    assert result["migration_files_found"] == ["migrations/001_users.sql"]
    assert result["drift_detected"] is True
    assert result["column_drifts"][0]["table"] == "users"
    assert result["column_drifts"][0]["missing_in_db"] == ["username"]


def test_migration_drift_parses_multiple_statements_and_quoted_semicolons(tmp_path: Path) -> None:
    migration_dir = tmp_path / "db" / "migrations"
    migration_dir.mkdir(parents=True)
    (migration_dir / "001_schema.sql").write_text(
        "CREATE TABLE first_table (value TEXT DEFAULT 'left;right'); "
        "CREATE TABLE second_table (id INTEGER);\n",
        encoding="utf-8",
    )
    db_file = tmp_path / "app.db"
    with sqlite3.connect(db_file):
        pass

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
    result = engine.migration_drift(str(tmp_path), str(db_file))

    assert result["success"] is True
    assert result["migration_files_found"] == ["db/migrations/001_schema.sql"]
    assert set(result["missing_tables_in_db"]) == {"first_table", "second_table"}


def test_migration_drift_does_not_claim_sync_without_table_ddl(tmp_path: Path) -> None:
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    (migration_dir / "001_data.sql").write_text(
        "INSERT INTO users (id) VALUES (1);\n",
        encoding="utf-8",
    )
    db_file = tmp_path / "app.db"
    with sqlite3.connect(db_file) as con:
        con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
    result = engine.migration_drift(str(tmp_path), str(db_file))

    assert result["success"] is False
    assert "no supported table schema DDL" in result["error"]


def test_migration_drift_reports_live_only_columns(tmp_path: Path) -> None:
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    (migration_dir / "001_users.sql").write_text(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT);\n",
        encoding="utf-8",
    )
    db_file = tmp_path / "app.db"
    with sqlite3.connect(db_file) as con:
        con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, legacy TEXT)")

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
    result = engine.migration_drift(str(tmp_path), str(db_file))

    assert result["success"] is True
    assert result["drift_detected"] is True
    assert result["column_drifts"] == [
        {"table": "users", "missing_in_db": [], "extra_in_db": ["legacy"]}
    ]
    assert result["drift"]["users"]["missing_in_code"] == ["legacy"]


def test_migration_drift_does_not_report_sync_without_live_database(tmp_path: Path) -> None:
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})

    result = engine.migration_drift(str(tmp_path))

    assert result["success"] is False
    assert result["status"] == "database_missing"
    assert result["in_sync"] is None
    assert result["drift_detected"] is None


def test_migration_drift_does_not_claim_sync_without_schema_source(tmp_path: Path) -> None:
    db_file = tmp_path / "app.db"
    with sqlite3.connect(db_file) as con:
        con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
    result = engine.migration_drift(str(tmp_path), str(db_file))

    assert result["success"] is False
    assert result["status"] == "schema_source_unavailable"
    assert result["in_sync"] is None
    assert result["drift_detected"] is None


def test_migration_drift_rejects_database_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside_db = tmp_path / "outside.db"
    with sqlite3.connect(outside_db) as con:
        con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
    result = engine.migration_drift(str(root), str(outside_db))

    assert result["success"] is False
    assert result["status"] == "database_path_outside_root"
    assert result["in_sync"] is None
    assert result["drift_detected"] is None


def test_migration_drift_bounds_live_schema_column_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    db_file = tmp_path / "app.db"
    with sqlite3.connect(db_file) as con:
        con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    (migration_dir / "001_users.sql").write_text(
        "CREATE TABLE users (id INTEGER PRIMARY KEY);\n", encoding="utf-8"
    )
    monkeypatch.setattr(deterministic, "_MAX_SCHEMA_DB_COLUMNS", 0)

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
    result = engine.migration_drift(str(tmp_path), str(db_file))

    assert result["success"] is False
    assert result["status"] == "database_inspection_failed"
    assert result["in_sync"] is None
    assert result["drift_detected"] is None


def test_migration_drift_rejects_oversized_database_before_open(
    tmp_path: Path, monkeypatch
) -> None:
    db_file = tmp_path / "app.db"
    with sqlite3.connect(db_file):
        pass
    monkeypatch.setattr(deterministic, "_MAX_SCHEMA_DB_BYTES", 0)

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
    result = engine.migration_drift(str(tmp_path), str(db_file))

    assert result["success"] is False
    assert result["status"] == "database_size_limit_exceeded"
    assert result["in_sync"] is None
    assert result["drift_detected"] is None


def test_migration_drift_bounds_directory_entry_scan(
    tmp_path: Path, monkeypatch
) -> None:
    db_file = tmp_path / "app.db"
    with sqlite3.connect(db_file):
        pass
    (tmp_path / "models.py").write_text("class User: pass\n", encoding="utf-8")
    monkeypatch.setattr(deterministic, "_MAX_SCHEMA_SCAN_ENTRIES", 1)

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
    result = engine.migration_drift(str(tmp_path), str(db_file))

    assert result["success"] is False
    assert result["status"] == "schema_scan_budget_exceeded"
    assert result["in_sync"] is None
    assert result["drift_detected"] is None


def test_migration_drift_bounds_python_model_fallback_scan(
    tmp_path: Path, monkeypatch
) -> None:
    db_file = tmp_path / "app.db"
    with sqlite3.connect(db_file) as con:
        con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    (tmp_path / "one.py").write_text("class One: pass\n", encoding="utf-8")
    (tmp_path / "two.py").write_text("class Two: pass\n", encoding="utf-8")
    monkeypatch.setattr(deterministic, "_MAX_SCHEMA_SCAN_FILES", 1)

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
    result = engine.migration_drift(str(tmp_path), str(db_file))

    assert result["success"] is False
    assert result["status"] == "schema_scan_budget_exceeded"
    assert result["in_sync"] is None
    assert result["drift_detected"] is None


def test_migration_drift_does_not_claim_sync_when_python_source_cannot_be_parsed(
    tmp_path: Path,
) -> None:
    db_file = tmp_path / "app.db"
    with sqlite3.connect(db_file) as con:
        con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    (tmp_path / "models.py").write_text("class Broken(:\n", encoding="utf-8")

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
    result = engine.migration_drift(str(tmp_path), str(db_file))

    assert result["success"] is False
    assert result["status"] == "schema_scan_failed"
    assert result["in_sync"] is None
    assert result["drift_detected"] is None
