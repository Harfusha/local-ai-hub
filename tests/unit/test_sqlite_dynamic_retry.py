"""Deferred bundle regressions: bounded busy retry and isolated writer contention."""
import sqlite3
from contextlib import closing

import pytest

from local_ai_hub import sqlite_support as support


def test_exponential_jitter_ranges_are_capped_and_attempts_bounded(monkeypatch):
    ranges, delays, attempts = [], [], []

    def choose(low, high):
        ranges.append((low, high))
        return (low + high) / 2

    def locked():
        attempts.append(True)
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(support.random, "uniform", choose)
    monkeypatch.setattr(support.time, "sleep", delays.append)
    with pytest.raises(sqlite3.OperationalError):
        support.retry_busy(locked, retries=5, base_delay_seconds=0.1, max_delay_seconds=0.4)
    assert len(attempts) == 5
    assert ranges == [(0.05, 0.1), (0.1, 0.2), (0.2, 0.4), (0.2, 0.4)]
    assert delays == [sum(bounds) / 2 for bounds in ranges]


def test_non_busy_errors_are_never_retried(monkeypatch):
    attempts = []
    monkeypatch.setattr(support.time, "sleep", lambda _delay: pytest.fail("non-busy errors must not sleep"))

    def malformed():
        attempts.append(True)
        raise sqlite3.OperationalError("no such table: absent")

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        support.retry_busy(malformed)
    assert attempts == [True]


def test_real_writer_contention_releases_between_bounded_attempts(tmp_path, monkeypatch):
    database = tmp_path / "only-test.sqlite3"
    with closing(support.connect_sqlite(database, timeout_seconds=0.01)) as owner:
        owner.execute("CREATE TABLE values_table(value INTEGER)")
        owner.commit()
        owner.execute("BEGIN IMMEDIATE")
        owner.execute("INSERT INTO values_table VALUES(1)")
        with closing(support.connect_sqlite(database, timeout_seconds=0.01)) as contender:
            attempts = []
            delays = []

            def release(delay):
                delays.append(delay)
                owner.commit()

            def insert():
                attempts.append(True)
                contender.execute("INSERT INTO values_table VALUES(2)")
                contender.commit()
                return "written"

            monkeypatch.setattr(support.time, "sleep", release)
            assert support.retry_busy(insert, retries=3, jitter=False) == "written"
            assert len(attempts) == 2
            assert delays == [0.015]
            assert contender.execute("SELECT value FROM values_table ORDER BY value").fetchall() == [(1,), (2,)]
