from __future__ import annotations

import concurrent.futures
from pathlib import Path
import sqlite3
import pytest

from local_ai_hub.preprocess_write_actor import PreprocessWriteActor


def test_preprocess_write_actor_basic_and_concurrency(tmp_path: Path) -> None:
    db_path = tmp_path / "test_actor.sqlite3"
    actor = PreprocessWriteActor(db_path)
    actor.start()

    try:
        # Create table via actor
        actor.submit(lambda con: con.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, val TEXT)"))

        # Submit multiple concurrent writes
        def insert_val(i: int) -> int:
            return actor.submit(lambda con: con.execute("INSERT INTO items (val) VALUES (?)", (f"val_{i}",)).rowcount)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(insert_val, range(100)))

        assert all(r == 1 for r in results)

        # Verify count
        count = actor.submit(lambda con: con.execute("SELECT COUNT(*) FROM items").fetchone()[0])
        assert count == 100

    finally:
        actor.stop()


def test_preprocess_write_actor_exception_handling(tmp_path: Path) -> None:
    db_path = tmp_path / "test_err.sqlite3"
    actor = PreprocessWriteActor(db_path)
    actor.start()

    try:
        actor.submit(lambda con: con.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, val TEXT UNIQUE)"))
        actor.submit(lambda con: con.execute("INSERT INTO items (val) VALUES (?)", ("unique_key",)))

        # Submitting duplicate key should raise sqlite3.IntegrityError
        with pytest.raises(sqlite3.IntegrityError):
            actor.submit(lambda con: con.execute("INSERT INTO items (val) VALUES (?)", ("unique_key",)))

        # Actor should still be alive and accept subsequent writes
        res = actor.submit(lambda con: con.execute("INSERT INTO items (val) VALUES (?)", ("another_key",)).rowcount)
        assert res == 1

    finally:
        actor.stop()


def test_preprocess_write_actor_does_not_report_success_before_commit(tmp_path: Path) -> None:
    db_path = tmp_path / "deferred_fk.sqlite3"
    con = sqlite3.connect(db_path)
    try:
        con.executescript(
            "CREATE TABLE parent (id INTEGER PRIMARY KEY);"
            "CREATE TABLE child (parent_id INTEGER, "
            "FOREIGN KEY(parent_id) REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED);"
        )
    finally:
        con.close()

    actor = PreprocessWriteActor(db_path)
    actor.start()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            actor.submit(
                lambda con: (
                    con.execute("INSERT INTO child (parent_id) VALUES (404)"),
                    "inserted",
                )[1]
            )
    finally:
        actor.stop()

    con = sqlite3.connect(db_path)
    try:
        assert con.execute("SELECT COUNT(*) FROM child").fetchone()[0] == 0
    finally:
        con.close()
