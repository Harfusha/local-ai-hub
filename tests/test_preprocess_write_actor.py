from __future__ import annotations

import concurrent.futures
from contextlib import closing
from pathlib import Path
import sqlite3
import threading
import time
import pytest

from local_ai_hub import preprocess_write_actor
from local_ai_hub.preprocess import ProjectPreprocessor
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


def test_write_queue_saturation_uses_backoff() -> None:
    from local_ai_hub.preprocess import _RetryablePreprocessingError
    from local_ai_hub.preprocess_write_actor import WriteQueueTimeout

    class SaturatedActor:
        is_alive = True

        def is_current_thread(self) -> bool:
            return False

        def submit(self, *_args, **_kwargs):
            raise WriteQueueTimeout("write did not start before its queue deadline")

    processor = object.__new__(ProjectPreprocessor)
    processor._write_actor = SaturatedActor()

    with pytest.raises(_RetryablePreprocessingError) as raised:
        processor._write_retry(lambda _connection: None)

    assert raised.value.retry_after_seconds == 30.0


def test_live_write_queue_timeout_uses_backoff_and_cancels_queued_callback(tmp_path: Path) -> None:
    from local_ai_hub.preprocess import _RetryablePreprocessingError

    actor = PreprocessWriteActor(tmp_path / "saturated.sqlite3")
    actor.start()
    processor = object.__new__(ProjectPreprocessor)
    processor._write_actor = actor
    started = threading.Event()
    release = threading.Event()
    timed_out_callback = threading.Event()

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            active = executor.submit(
                actor.submit,
                lambda _con: (started.set(), release.wait(timeout=2))[1],
            )
            try:
                assert started.wait(timeout=2)
                with pytest.raises(_RetryablePreprocessingError) as raised:
                    processor._write_retry(
                        lambda _con: timed_out_callback.set(),
                        actor_timeout=0.01,
                    )

                assert raised.value.retry_after_seconds == 30.0
            finally:
                release.set()

            assert active.result(timeout=2) is True
            assert actor.submit(lambda _con: "queue drained") == "queue drained"

        assert not timed_out_callback.is_set()
    finally:
        release.set()
        actor.stop(timeout=2)


@pytest.mark.parametrize("use_preprocessor", [False, True])
def test_nested_write_shares_outer_transaction_and_rolls_back_locally(tmp_path: Path, use_preprocessor: bool) -> None:
    db_path = tmp_path / "nested.sqlite3"
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute("CREATE TABLE writes (value TEXT NOT NULL)")
    actor = PreprocessWriteActor(db_path, connection_timeout_seconds=0.05)
    processor = object.__new__(ProjectPreprocessor)
    processor._write_actor = actor
    processor._db_lock = threading.Lock()
    processor._connect = lambda: sqlite3.connect(db_path, timeout=0.05)
    processor._sqlite_write_retries = 0
    submit_nested = processor._write_retry if use_preprocessor else actor.submit

    def write_batch(con, *, abort=False):
        con.execute("INSERT INTO writes VALUES ('outer')")

        def rejected(nested):
            nested.execute("INSERT INTO writes VALUES ('rejected')")
            raise ValueError("rollback nested")

        with pytest.raises(ValueError, match="rollback nested"):
            submit_nested(rejected)
        submit_nested(lambda nested: nested.execute("INSERT INTO writes VALUES ('nested')"))
        if abort:
            raise RuntimeError("rollback outer")

    actor.start()
    try:
        actor.submit(write_batch)
        with pytest.raises(RuntimeError, match="rollback outer"):
            actor.submit(lambda con: write_batch(con, abort=True))
    finally:
        actor.stop()
    with closing(sqlite3.connect(db_path)) as con:
        assert con.execute("SELECT value FROM writes ORDER BY rowid").fetchall() == [("outer",), ("nested",)]


@pytest.mark.parametrize("failure_path", ["rollback", "worker_exit"])
def test_cancellation_during_failure_delivery_does_not_strand_other_writes(tmp_path: Path, failure_path: str) -> None:
    class CancelOnError(concurrent.futures.Future):
        def set_exception(self, exception):
            assert self.cancel()
            super().set_exception(exception)

    actor = PreprocessWriteActor(tmp_path / "failure_race.sqlite3")
    cancelled = CancelOnError()
    following = concurrent.futures.Future()
    operations = [(lambda _con: None, cancelled), (lambda _con: None, following)]

    if failure_path == "rollback":
        actor._fail_batch(operations, ValueError("synthetic batch failure"))
        expected_error = preprocess_write_actor.BatchRolledBackError
    else:
        for index, operation in enumerate(operations):
            actor._queue.put((1, index, operation))
        actor._fail_queued()
        expected_error = RuntimeError

    assert cancelled.cancelled()
    with pytest.raises(expected_error):
        following.result(timeout=0)
    assert actor._queue.unfinished_tasks == 0


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


def test_timeout_of_running_write_reports_unknown_outcome(tmp_path: Path) -> None:
    db_path = tmp_path / "timeout.sqlite3"
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute("CREATE TABLE writes (value TEXT NOT NULL)")

    actor = PreprocessWriteActor(db_path)
    actor.start()
    started = threading.Event()
    release = threading.Event()

    def write(con: sqlite3.Connection) -> int:
        started.set()
        assert release.wait(timeout=2)
        return con.execute("INSERT INTO writes VALUES ('committed')").rowcount

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(actor.submit, write, timeout=0.01)
            assert started.wait(timeout=2)
            with pytest.raises(TimeoutError) as exc_info:
                result.result(timeout=1)
            assert type(exc_info.value).__name__ == "WriteOutcomeUnknown"
            release.set()
            assert actor.submit(lambda con: con.execute("SELECT COUNT(*) FROM writes").fetchone()[0]) == 1
    finally:
        release.set()
        actor.stop()


def test_fatal_worker_exit_fails_queued_write_future(tmp_path: Path) -> None:
    actor = PreprocessWriteActor(tmp_path / "fatal.sqlite3", max_batch_size=1)
    real_get = actor._queue.get
    first_get = threading.Event()

    def fail_after_first(*args, **kwargs):
        if first_get.is_set() and kwargs.get("block", True):
            raise RuntimeError("injected fatal worker failure")
        first_get.set()
        return real_get(*args, **kwargs)

    actor._queue.get = fail_after_first  # type: ignore[method-assign]
    actor.start()
    started = threading.Event()
    release = threading.Event()

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(
                actor.submit,
                lambda _con: (started.set(), release.wait(timeout=2))[1],
            )
            assert started.wait(timeout=2)
            pending = executor.submit(actor.submit, lambda _con: "never executed")
            deadline = time.monotonic() + 2
            while actor._queue.qsize() < 1 and time.monotonic() < deadline:
                time.sleep(0.001)
            assert actor._queue.qsize() == 1
            release.set()
            first.result(timeout=2)
            with pytest.raises(RuntimeError, match="worker stopped"):
                pending.result(timeout=2)
        assert not actor._thread.is_alive()
    finally:
        release.set()
        actor.stop()


def test_rolled_back_batch_is_not_replayed_after_callback_side_effects(tmp_path: Path) -> None:
    db_path = tmp_path / "batch_rollback.sqlite3"
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute("CREATE TABLE writes (value TEXT NOT NULL)")

    actor = PreprocessWriteActor(db_path, max_batch_size=4)
    real_get = actor._queue.get
    allow_get = threading.Event()
    waiting_for_batch = threading.Event()

    def hold_first_get(*args, **kwargs):
        waiting_for_batch.set()
        assert allow_get.wait(timeout=2)
        return real_get(*args, **kwargs)

    actor._queue.get = hold_first_get  # type: ignore[method-assign]
    actor.start()
    effects: list[str] = []

    def first(con: sqlite3.Connection) -> None:
        effects.append("first")
        con.execute("INSERT INTO writes VALUES ('first')")

    def second(_con: sqlite3.Connection) -> None:
        effects.append("second")
        raise ValueError("abort batch")

    try:
        assert waiting_for_batch.wait(timeout=2)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            first_result = executor.submit(actor.submit, first)
            second_result = executor.submit(actor.submit, second)
            deadline = time.monotonic() + 2
            while actor._queue.qsize() < 2 and time.monotonic() < deadline:
                time.sleep(0.001)
            assert actor._queue.qsize() == 2
            allow_get.set()
            for result in (first_result, second_result):
                with pytest.raises(RuntimeError, match="batch was rolled back"):
                    result.result(timeout=2)
        assert effects == ["first", "second"]
        with closing(sqlite3.connect(db_path)) as con:
            assert con.execute("SELECT COUNT(*) FROM writes").fetchone()[0] == 0
    finally:
        allow_get.set()
        actor.stop()


def test_submit_during_timed_out_stop_does_not_write_concurrently(tmp_path: Path) -> None:
    actor = PreprocessWriteActor(tmp_path / "stop_timeout.sqlite3")
    actor.start()
    started = threading.Event()
    release = threading.Event()
    direct_calls: list[str] = []

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            active = executor.submit(
                actor.submit,
                lambda _con: (started.set(), release.wait(timeout=2))[1],
            )
            assert started.wait(timeout=2)
            actor.stop(timeout=0.01)
            assert actor.is_alive
            with pytest.raises(RuntimeError, match="stopping"):
                actor.submit(lambda _con: direct_calls.append("concurrent"))
            release.set()
            active.result(timeout=2)
        actor.stop(timeout=2)
        assert actor._thread is not None and not actor._thread.is_alive()
        assert direct_calls == []
    finally:
        release.set()
        actor.stop(timeout=2)
