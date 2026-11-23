import sqlite3
import threading
from contextlib import closing

import pytest

from local_ai_hub.preprocess import ProjectPreprocessor, _RetryablePreprocessingError


@pytest.fixture
def scheduler(tmp_path, monkeypatch):
    db = tmp_path / "projects.sqlite"
    def connect():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        return con
    with closing(connect()) as con:
        con.execute("""CREATE TABLE projects (
            root TEXT PRIMARY KEY, status TEXT, phase TEXT, paused INTEGER DEFAULT 0,
            force_refresh INTEGER DEFAULT 0, last_requested_at REAL DEFAULT 0,
            updated_at REAL DEFAULT 0, retry_after REAL DEFAULT 0, next_check_at REAL DEFAULT 0
        )""")
        con.commit()
    instance = ProjectPreprocessor.__new__(ProjectPreprocessor)
    instance._connect = connect
    instance._db_lock = threading.RLock()
    instance._sqlite_write_retries = 6
    instance.max_preprocessing_projects = 2
    instance._watcher_active = True
    monkeypatch.setattr("local_ai_hub.preprocess.time.time", lambda: 10000.0)
    return instance, connect


def add(connect, root, status, updated, requested, phase="files"):
    with closing(connect()) as con:
        con.execute("INSERT INTO projects(root,status,phase,updated_at,last_requested_at) VALUES(?,?,?,?,?)",
                    (root, status, phase, updated, requested))
        con.commit()


def test_recent_repository_wins_next_step(scheduler):
    instance, connect = scheduler
    add(connect, "older", "running", 9990, 9000)
    add(connect, "active", "running", 9995, 9999)
    assert instance._next_cpu_project()["root"] == "active"
    assert instance._next_gpu_project()["root"] == "active"


def test_cpu_and_gpu_selection_rebalance_at_state_priority(scheduler):
    instance, connect = scheduler
    add(connect, "active", "running", 9999, 9999)
    priorities = []

    def write_retry(operation, *, actor_priority=1, **_kwargs):
        priorities.append(actor_priority)
        with closing(connect()) as con:
            result = operation(con)
            con.commit()
            return result

    instance._write_retry = write_retry

    assert instance._next_cpu_project()["root"] == "active"
    assert instance._next_gpu_project()["root"] == "active"
    assert priorities == [0, 0]


def test_cpu_selection_survives_retryable_rebalance_failure(scheduler):
    instance, connect = scheduler
    add(connect, "active", "running", 9999, 9999)

    def saturated(*_args, **_kwargs):
        raise _RetryablePreprocessingError("preprocessing write queue is saturated", 30.0)

    instance._write_retry = saturated
    assert instance._next_cpu_project()["root"] == "active"


def test_waiting_project_outside_admitted_slots_cannot_run_on_gpu(scheduler):
    instance, connect = scheduler
    instance.max_preprocessing_projects = 1
    add(connect, "active", "running", 9999, 9999, phase="hash")
    add(connect, "waiting", "waiting", 9998, 9000)
    assert instance._next_gpu_project() is None


def test_recently_requested_project_gets_admitted_slot(scheduler):
    instance, connect = scheduler
    instance.max_preprocessing_projects = 1
    add(connect, "inactive", "queued", 9499, 0)
    add(connect, "active", "waiting", 9500, 9999)

    with closing(connect()) as con:
        instance._rebalance_processing_slots(con)
        con.commit()
        states = {row[0]: row[1] for row in con.execute("SELECT root,status FROM projects")}

    assert states == {"inactive": "waiting", "active": "queued"}


def test_reactivation_preserves_stale_priority_for_admission(scheduler):
    instance, connect = scheduler
    instance.max_preprocessing_projects = 1
    add(connect, "stale-oldest", "queued", 9000, 9990)
    add(connect, "stale", "queued", 9200, 0)
    add(connect, "reactivated", "waiting", 9500, 0)

    def write_retry(operation, **_kwargs):
        with closing(connect()) as con:
            result = operation(con)
            con.commit()
            return result

    instance._root = lambda root: root
    instance._write_retry = write_retry
    instance._wake_all = lambda: None
    instance.status = lambda root=None: {"root": root}

    instance.resume("reactivated")

    with closing(connect()) as con:
        updated_at = con.execute(
            "SELECT updated_at FROM projects WHERE root='reactivated'"
        ).fetchone()[0]
    assert updated_at == 9500

    assert instance._next_cpu_project()["root"] == "reactivated"


def test_recent_resume_reclaims_queued_slot_ahead_of_unowned_stale_work(scheduler):
    instance, connect = scheduler
    instance.max_preprocessing_projects = 1
    add(connect, "stale-waiting", "waiting", 9000, 9999)
    add(connect, "reactivated", "waiting", 9999, 0)

    def write_retry(operation, **_kwargs):
        with closing(connect()) as con:
            result = operation(con)
            con.commit()
            return result

    instance._root = lambda root: root
    instance._write_retry = write_retry
    instance._wake_all = lambda: None
    instance.status = lambda root=None: {"root": root}

    instance.resume("reactivated")

    assert instance._next_cpu_project()["root"] == "reactivated"


def test_cpu_worker_survives_locked_queue_database(scheduler, monkeypatch):
    instance, _ = scheduler
    instance.cfg = {"startup_delay_seconds": 0, "poll_seconds": 0.2}
    instance.cpu_priority = 0
    instance._stop = threading.Event()
    instance._paused = threading.Event()
    instance._stats_lock = threading.Lock()
    instance._stats = {"loops": 0, "yields": 0}
    instance.cpu_runs_during_foreground = True
    instance._background_work_allowed = lambda: True

    class StopOnWait:
        def wait(self, _timeout):
            instance._stop.set()

        def clear(self):
            pass

    instance._cpu_wakeup = StopOnWait()

    def locked_queue(**_kwargs):
        raise sqlite3.OperationalError("database is locked")

    instance._next_cpu_project = locked_queue
    monkeypatch.setattr("local_ai_hub.preprocess.set_current_thread_priority", lambda _priority: None)

    instance._cpu_loop()

    assert instance._stats["yields"] == 1


def test_gpu_worker_survives_locked_queue_database(scheduler):
    instance, _ = scheduler
    instance.cfg = {"startup_delay_seconds": 0, "poll_seconds": 0.2}
    instance._stop = threading.Event()
    instance._paused = threading.Event()
    instance._background_work_allowed = lambda: True
    instance.background_gpu = type("ReadyGpu", (), {"ready": lambda _self: True})()

    class StopOnWait:
        def __init__(self):
            self.wait_count = 0

        def wait(self, _timeout):
            self.wait_count += 1
            instance._stop.set()

        def clear(self):
            pass

    instance._gpu_wakeup = StopOnWait()

    def locked_queue(**_kwargs):
        raise sqlite3.OperationalError("database is locked")

    instance._next_gpu_project = locked_queue

    instance._gpu_loop()

    assert instance._gpu_wakeup.wait_count == 1


def test_gpu_worker_survives_write_actor_timeout(scheduler):
    instance, _ = scheduler
    instance.cfg = {"startup_delay_seconds": 0, "poll_seconds": 0.2}
    instance._stop = threading.Event()
    instance._paused = threading.Event()
    instance._background_work_allowed = lambda: True
    instance.background_gpu = type("ReadyGpu", (), {"ready": lambda _self: True})()

    class StopAfterRetry:
        def __init__(self):
            self.wait_count = 0

        def wait(self, _timeout):
            self.wait_count += 1
            if self.wait_count == 2:
                instance._stop.set()

        def clear(self):
            pass

    instance._gpu_wakeup = StopAfterRetry()
    calls = []

    def timeout_then_empty():
        calls.append(True)
        if len(calls) == 1:
            raise TimeoutError()
        return None

    instance._next_gpu_project = timeout_then_empty
    instance._gpu_loop()

    assert len(calls) == 2


def test_stale_waiting_project_eventually_gets_slot(scheduler):
    instance, connect = scheduler
    instance.max_preprocessing_projects = 1
    add(connect, "active", "running", 9999, 9999)
    add(connect, "waiting", "waiting", 9600, 9000)
    assert instance._next_cpu_project()["root"] == "waiting"


def test_recent_activity_does_not_permanently_starve_another_project(scheduler, monkeypatch):
    instance, connect = scheduler
    instance.max_preprocessing_projects = 1
    now = [10000.0]
    monkeypatch.setattr("local_ai_hub.preprocess.time.time", lambda: now[0])
    add(connect, "active", "running", 9990, 9999)
    add(connect, "waiting", "waiting", 9990, 9000)
    assert instance._next_cpu_project()["root"] == "active"
    now[0] += 301
    with closing(connect()) as con:
        con.execute("UPDATE projects SET updated_at=?,last_requested_at=? WHERE root='active'", (now[0], now[0]))
        con.commit()
    assert instance._next_cpu_project()["root"] == "waiting"


def test_gpu_does_not_select_a_project_in_retry_cooldown(scheduler):
    instance, connect = scheduler
    instance._file_card_enrichment_enabled = lambda: False
    add(connect, "cooldown", "error", 9990, 9999)
    with closing(connect()) as con:
        con.execute("UPDATE projects SET retry_after=10100 WHERE root='cooldown'")
        con.commit()
    assert instance._next_gpu_project() is None
