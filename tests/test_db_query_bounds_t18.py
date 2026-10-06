from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import local_ai_hub.http_server as http_server


def test_read_only_db_query_stops_after_bounded_sqlite_work(monkeypatch, tmp_path) -> None:
    database = tmp_path / "agent_state.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE numbers (value INTEGER NOT NULL)")
        connection.executemany("INSERT INTO numbers VALUES (?)", ((value,) for value in range(300)))
        connection.commit()
    finally:
        connection.close()

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"server": {"state_dir": str(tmp_path)}}))

    result = http_server.Handler._handle_db_query(
        None,
        "agent_state",
        "SELECT count(*) FROM numbers a CROSS JOIN numbers b CROSS JOIN numbers c",
    )

    assert result == {"success": False, "error": "query execution exceeded work limit"}


def test_read_only_db_query_caps_returned_rows_at_100(monkeypatch, tmp_path) -> None:
    database = tmp_path / "agent_state.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE numbers (value INTEGER NOT NULL)")
        connection.executemany("INSERT INTO numbers VALUES (?)", ((value,) for value in range(300)))
        connection.commit()
    finally:
        connection.close()

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"server": {"state_dir": str(tmp_path)}}))
    result = http_server.Handler._handle_db_query(None, "agent_state", "SELECT value FROM numbers ORDER BY value")

    assert result["success"] is True
    assert result["count"] == 100
    assert result["rows"][0] == [0]
    assert result["rows"][-1] == [99]


def test_read_only_db_query_rejects_results_over_byte_budget(monkeypatch, tmp_path) -> None:
    database = tmp_path / "agent_state.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE payloads (value TEXT NOT NULL)")
        connection.executemany("INSERT INTO payloads VALUES (?)", (("x" * 8_192,) for _ in range(40)))
        connection.commit()
    finally:
        connection.close()

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"server": {"state_dir": str(tmp_path)}}))
    result = http_server.Handler._handle_db_query(None, "agent_state", "SELECT value FROM payloads")

    assert result == {"success": False, "error": "query result exceeded byte limit"}
