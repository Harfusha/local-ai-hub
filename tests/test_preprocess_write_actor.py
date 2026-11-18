from __future__ import annotations

import concurrent.futures
from pathlib import Path
import sqlite3
import threading
import time
import pytest

from local_ai_hub import preprocess_write_actor
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


def test_preprocess_write_actor_future_waits_for_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "commit_gate.sqlite3"
    con = sqlite3.connect(db_path)
    try:
        con.execute("CREATE TABLE items (value TEXT NOT NULL)")
    finally:
        con.close()

    real_connect = preprocess_write_actor.connect_sqlite
    commit_started = threading.Event()
    allow_commit = threading.Event()

    class PausedCommitConnection:
        def __init__(self, connection: sqlite3.Connection) -> None:
            self._connection = connection

        def __getattr__(self, name: str):
            return getattr(self._connection, name)

        def commit(self) -> None:
            commit_started.set()
            if not allow_commit.wait(timeout=2):
                raise TimeoutError("test did not release commit")
            self._connection.commit()

        def execute(self, sql: str, *args, **kwargs):
            if isinstance(sql, str) and sql.strip().upper() == "COMMIT":
                commit_started.set()
                if not allow_commit.wait(timeout=2):
                    raise TimeoutError("test did not release commit")
            return self._connection.execute(sql, *args, **kwargs)

    monkeypatch.setattr(
        preprocess_write_actor,
        "connect_sqlite",
        lambda *args, **kwargs: PausedCommitConnection(real_connect(*args, **kwargs)),
    )

    captured_futures: list[concurrent.futures.Future[object]] = []
    real_future = concurrent.futures.Future

    class CapturedFuture(real_future):
        def __init__(self) -> None:
            super().__init__()
            captured_futures.append(self)

    monkeypatch.setattr(concurrent.futures, "Future", CapturedFuture)

    actor = PreprocessWriteActor(db_path)
    actor.start()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(
                actor.submit,
                lambda connection: connection.execute("INSERT INTO items VALUES ('written')").rowcount,
            )
            try:
                assert commit_started.wait(timeout=2)
                assert len(captured_futures) == 1
                assert not captured_futures[0].done()
            finally:
                allow_commit.set()

            assert result.result(timeout=2) == 1
            assert captured_futures[0].done()
    finally:
        actor.stop()


def test_preprocess_write_actor_prioritizes_project_state_writes(tmp_path: Path) -> None:
    actor = PreprocessWriteActor(tmp_path / "priority.sqlite3", max_batch_size=1)
    actor.start()
    started = threading.Event()
    release = threading.Event()
    order: list[str] = []

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            first = executor.submit(
                actor.submit,
                lambda _con: (started.set(), release.wait(timeout=2))[1],
            )
            assert started.wait(timeout=2)

            background = executor.submit(actor.submit, lambda _con: order.append("background"))
            deadline = time.monotonic() + 2
            while actor._queue.qsize() < 1 and time.monotonic() < deadline:
                time.sleep(0.001)
            assert actor._queue.qsize() == 1

            project_state = executor.submit(
                actor.submit,
                lambda _con: order.append("project_state"),
                priority=0,
            )
            deadline = time.monotonic() + 2
            while actor._queue.qsize() < 2 and time.monotonic() < deadline:
                time.sleep(0.001)
            assert actor._queue.qsize() == 2

            release.set()
            first.result(timeout=2)
            project_state.result(timeout=2)
            background.result(timeout=2)

        assert order == ["project_state", "background"]
    finally:
        release.set()
        actor.stop()
