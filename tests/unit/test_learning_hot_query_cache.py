from __future__ import annotations

import sqlite3
import threading
import time
from types import SimpleNamespace

from local_ai_hub import learning
from local_ai_hub.learning import UsageLearner


def test_record_does_not_wait_on_a_locked_learning_database(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    learner = UsageLearner({"server": {"state_dir": str(tmp_path / "state")}})
    blocker = sqlite3.connect(learner.db_path, timeout=1.0)
    blocker.execute("BEGIN IMMEDIATE")

    try:
        started = time.perf_counter()
        learner.record(str(root), "locked learning query")
        elapsed = time.perf_counter() - started
    finally:
        blocker.rollback()
        blocker.close()

    assert elapsed < 0.5


def test_record_does_not_wait_for_an_in_process_learning_lock(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    learner = UsageLearner({"server": {"state_dir": str(tmp_path / "state")}})
    lock_held = threading.Event()
    release_lock = threading.Event()

    def hold_learning_lock():
        with learner._lock:
            lock_held.set()
            release_lock.wait(timeout=0.7)

    blocker = threading.Thread(target=hold_learning_lock)
    blocker.start()
    try:
        assert lock_held.wait(timeout=1.0)
        started = time.perf_counter()
        learner.record(str(root), "concurrent learning query")
        elapsed = time.perf_counter() - started
    finally:
        release_lock.set()
        blocker.join(timeout=1.0)

    assert not blocker.is_alive()
    assert elapsed < 0.5


def test_hot_query_cache_reuses_reads_and_record_invalidates_immediately(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    learner = UsageLearner({"server": {"state_dir": str(tmp_path / "state")}})
    learner.record(str(root), "first query")

    connect_count = 0
    connect = learner._connect

    def counted_connect(*, timeout_seconds=5.0):
        nonlocal connect_count
        connect_count += 1
        return connect(timeout_seconds=timeout_seconds)

    monkeypatch.setattr(learner, "_connect", counted_connect)

    initial = learner.hot_queries(str(root), 4)
    assert initial == ["first query"]
    assert learner.hot_queries(str(root), 4) == initial
    assert connect_count == 1

    learner.record(str(root), "second query")
    learner.record(str(root), "second query")
    learner.record(str(root), "second query")

    assert connect_count == 4
    assert learner.hot_queries(str(root), 4) == ["second query", "first query"]
    assert connect_count == 5


def test_clear_invalidates_only_the_requested_root_or_all_roots(tmp_path):
    root_a = tmp_path / "repo-a"
    root_b = tmp_path / "repo-b"
    root_a.mkdir()
    root_b.mkdir()
    learner = UsageLearner({"server": {"state_dir": str(tmp_path / "state")}})
    learner.record(str(root_a), "alpha query")
    learner.record(str(root_b), "beta query")

    assert learner.hot_queries(str(root_a), 4) == ["alpha query"]
    assert learner.hot_queries(str(root_b), 4) == ["beta query"]

    learner.clear(str(root_a))
    assert learner.hot_queries(str(root_a), 4) == []
    assert learner.hot_queries(str(root_b), 4) == ["beta query"]

    learner.clear()
    assert learner.hot_queries(str(root_b), 4) == []


def test_hot_query_cache_expires_and_returns_a_copy(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    learner = UsageLearner({"server": {"state_dir": str(tmp_path / "state")}})
    learner.record(str(root), "fresh query")

    clock = [100.0]
    monkeypatch.setattr(learning, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    connect_count = 0
    connect = learner._connect

    def counted_connect(*, timeout_seconds=5.0):
        nonlocal connect_count
        connect_count += 1
        return connect(timeout_seconds=timeout_seconds)

    monkeypatch.setattr(learner, "_connect", counted_connect)

    first = learner.hot_queries(str(root), 4)
    first.append("caller mutation")
    assert learner.hot_queries(str(root), 4) == ["fresh query"]
    assert connect_count == 1

    clock[0] += learning._HOT_QUERY_CACHE_TTL_SECONDS + 0.01
    assert learner.hot_queries(str(root), 4) == ["fresh query"]
    assert connect_count == 2
