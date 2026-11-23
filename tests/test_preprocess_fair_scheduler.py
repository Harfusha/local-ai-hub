import concurrent.futures
import sqlite3
import threading
import time
from contextlib import closing

import pytest

from local_ai_hub.preprocess import ProjectPreprocessor, _RetryablePreprocessingError
from local_ai_hub.preprocess_write_actor import PreprocessWriteActor
from local_ai_hub.sqlite_support import initialize_wal


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
        con.execute("""CREATE TABLE file_refs (
            root TEXT, path TEXT, content_hash TEXT DEFAULT '', card_key TEXT, size INTEGER NOT NULL DEFAULT 0,
            updated_at REAL DEFAULT 0, PRIMARY KEY(root,path)
        )""")
        con.commit()

    instance = ProjectPreprocessor.__new__(ProjectPreprocessor)
    instance.db_path = db
    instance._connect = connect
    instance._db_lock = threading.RLock()
    instance._sqlite_write_retries = 1
    instance.max_preprocessing_projects = 4
    instance._watcher_active = True
    now = [1_000_000.0]
    monkeypatch.setattr("local_ai_hub.preprocess.time.time", lambda: now[0])
    instance._test_now = now
    return instance, connect


def add(connect, root, phase, *, updated_at, last_requested_at, status="running"):
    with closing(connect()) as con:
        con.execute(
            "INSERT INTO projects(root,status,phase,updated_at,last_requested_at) VALUES(?,?,?,?,?)",
            (root, status, phase, updated_at, last_requested_at),
        )
        con.commit()


def test_active_inventory_precedes_hash_even_when_hash_is_older(scheduler):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "hash-active", "hash", updated_at=now - 20, last_requested_at=now - 5)
    add(connect, "inventory-active", "inventory", updated_at=now - 10, last_requested_at=now - 5)

    assert instance._next_cpu_project()["root"] == "inventory-active"


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError("writer busy"),
        _RetryablePreprocessingError("writer queue saturated", retry_after_seconds=30.0),
    ],
    ids=["timeout", "queue-saturated"],
)
def test_cpu_selection_survives_a_busy_slot_rebalance_writer(scheduler, failure):
    instance, connect = scheduler
    add(connect, "runnable", "inventory", updated_at=0, last_requested_at=0, status="queued")
    submitted = {}

    def timed_out_write(operation, **kwargs):
        submitted.update(kwargs)
        raise failure

    instance._write_retry = timed_out_write

    assert instance._next_cpu_project(rebalance=True)["root"] == "runnable"
    assert submitted["actor_timeout"] < 1.0


def test_active_base_layer_precedes_rag(scheduler):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "rag-active", "rag", updated_at=now - 20, last_requested_at=now - 5)
    add(connect, "deterministic-active", "deterministic", updated_at=now - 10, last_requested_at=now - 5)

    assert instance._next_cpu_project()["root"] == "deterministic-active"


def test_active_rag_precedes_files_within_second_layer(scheduler):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "files-active", "files", updated_at=now - 20, last_requested_at=now - 5)
    add(connect, "rag-active", "rag", updated_at=now - 10, last_requested_at=now - 5)

    assert instance._next_cpu_project()["root"] == "rag-active"


def test_active_files_precede_optional_phases(scheduler):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "modules-active", "modules", updated_at=now - 20, last_requested_at=now - 5)
    add(connect, "files-active", "files", updated_at=now - 10, last_requested_at=now - 5)

    assert instance._next_cpu_project()["root"] == "files-active"


@pytest.mark.parametrize(
    ("earlier", "later"),
    [
        ("hash", "code_index"),
        ("code_index", "deterministic"),
        ("deterministic", "lexical"),
        ("lexical", "serena"),
        ("lexical", "rag"),
        ("rag", "files"),
        ("files", "serena"),
        ("serena", "serena_optional"),
        ("files", "serena_optional"),
        ("serena_optional", "modules"),
        ("modules", "project"),
        ("project", "hot_queries"),
    ],
)
def test_phase_order_beats_small_timestamp_differences(scheduler, earlier, later):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "later-phase", later, updated_at=now - 20, last_requested_at=now - 5)
    add(connect, "earlier-phase", earlier, updated_at=now - 10, last_requested_at=now - 5)

    assert instance._next_cpu_project()["root"] == "earlier-phase"


def test_legacy_serena_checkpoint_remains_schedulable(scheduler):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "legacy-serena", "serena", updated_at=now - 10, last_requested_at=now - 5)

    assert instance._next_cpu_project()["phase"] == "serena"


def test_new_projects_enter_lexical_directly_after_deterministic(scheduler):
    instance, _connect = scheduler
    transitions = []
    instance.deterministic = None
    instance._set_project = lambda root, **values: transitions.append((root, values))

    assert instance._step_deterministic({"root": "repo", "generation": 0}) is True
    assert transitions[-1][1]["phase"] == "lexical"


def test_deterministic_batch_timeout_splits_and_keeps_progress(scheduler):
    instance, connect = scheduler
    with closing(connect()) as con:
        con.execute("ALTER TABLE file_refs ADD COLUMN needs_hash INTEGER DEFAULT 0")
        con.executemany(
            "INSERT INTO file_refs(root,path,content_hash,needs_hash) VALUES(?,?,?,0)",
            [("repo", f"file_{index}.py", f"hash_{index}") for index in range(4)],
        )
        con.commit()

    class TimedBatch:
        def __init__(self):
            self.calls = []
            self.completed = []

        def prune(self, _root, _paths):
            return None

        def _connect(self):
            con = sqlite3.connect(":memory:")
            con.execute("CREATE TABLE files(root TEXT, path TEXT, content_hash TEXT)")
            return con

        def update_files_batch(self, _root, items):
            paths = [path for path, _digest in items]
            self.calls.append(paths)
            if len(paths) > 1:
                raise TimeoutError
            self.completed.extend(paths)
            return {"updated": 1, "cached": 0}

    deterministic = TimedBatch()
    progress = []
    instance.cfg = {"deterministic_files_per_step": 4}
    instance.deterministic = deterministic
    instance._missing_refs_checked_generations = set()
    instance._prune_missing_file_refs = lambda _root: None
    instance._stats_lock = threading.Lock()
    instance._stats = {"deterministic_files": 0}
    instance._record_progress = lambda root, count: progress.append((root, count))
    instance._set_project = lambda *_args, **_values: pytest.fail("successful split batches should not wait")

    assert instance._step_deterministic({"root": "repo", "generation": 0}) is True
    assert [len(batch) for batch in deterministic.calls] == [4, 2, 1, 1, 2, 1, 1]
    assert deterministic.completed == [f"file_{index}.py" for index in range(4)]
    assert instance._stats["deterministic_files"] == 4
    assert progress == [("repo", 4)]


def test_file_phase_enters_optional_serena_checkpoint(scheduler):
    instance, _connect = scheduler
    transitions = []
    instance.config = {"background_gpu": {}}
    instance.cfg = {"auto_recheck_seconds": 1800}
    instance._file_card_enrichment_enabled = lambda: False
    instance._find_next_files = lambda _root, _limit: []
    instance._set_project = lambda root, **values: transitions.append((root, values))

    assert instance._step_file_card({"root": "repo", "phase": "files"}) is True
    assert transitions[-1][1]["phase"] == "serena_optional"


@pytest.mark.parametrize(
    ("phase", "expected_next", "should_index"),
    [("serena", "lexical", False), ("serena_optional", "modules", True)],
)
def test_serena_checkpoint_routes_preserve_legacy_and_new_flow(
    scheduler, tmp_path, phase, expected_next, should_index
):
    instance, _connect = scheduler
    root = tmp_path / phase
    root.mkdir()
    transitions = []
    instance._background_work_allowed = lambda: True
    instance._yield = lambda: False
    project_transitions = []
    instance._set_project = lambda root, **values: project_transitions.append((root, values))
    instance._step_external_index = lambda _row, backend, next_phase: transitions.append((backend, next_phase)) or True

    assert instance._step({"root": str(root), "phase": phase, "status": "queued"}) is True
    assert transitions == ([("serena", expected_next)] if should_index else [])
    if should_index:
        assert project_transitions == [(str(root), {"status": "running"})]
    else:
        assert project_transitions == [
            (str(root), {"status": "running"}),
            (str(root), {"phase": expected_next}),
        ]


def test_gpu_worker_waits_for_active_cpu_layer(scheduler):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "files-active", "files", updated_at=now - 5, last_requested_at=now - 5)
    add(connect, "inventory-active", "inventory", updated_at=now - 10, last_requested_at=now - 5)

    assert instance._next_gpu_project() is None


def test_gpu_skips_locked_head_within_preferred_phase(scheduler):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "locked-files", "files", updated_at=now - 20, last_requested_at=now - 5)
    add(connect, "available-files", "files", updated_at=now - 10, last_requested_at=now - 5)
    instance._project_limit = lambda: 2
    lock = threading.Lock()
    lock.acquire()
    instance._step_locks_guard = threading.Lock()
    instance._step_locks = {"locked-files": lock}

    try:
        assert instance._next_gpu_project()["root"] == "available-files"
    finally:
        lock.release()


def test_gpu_does_not_skip_locked_preferred_phase(scheduler):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "locked-files", "files", updated_at=now - 20, last_requested_at=now - 5)
    add(connect, "available-modules", "modules", updated_at=now - 10, last_requested_at=now - 5)
    instance._project_limit = lambda: 2
    lock = threading.Lock()
    lock.acquire()
    instance._step_locks_guard = threading.Lock()
    instance._step_locks = {"locked-files": lock}

    try:
        assert instance._next_gpu_project() is None
    finally:
        lock.release()


def test_project_expires_at_24_hours_and_foreground_touch_reactivates_it(scheduler, tmp_path):
    instance, connect = scheduler
    now = instance._test_now[0]
    active_root = str(tmp_path / "active")
    inactive_root = str(tmp_path / "inactive")
    (tmp_path / "active").mkdir()
    (tmp_path / "inactive").mkdir()
    add(connect, active_root, "inventory", updated_at=now - 10, last_requested_at=now - 86_400 + 1)
    add(connect, inactive_root, "inventory", updated_at=now - 11, last_requested_at=now - 86_400 - 1)

    assert instance._next_cpu_project()["root"] == active_root

    instance._test_now[0] += 2
    assert instance._next_cpu_project()["root"] == inactive_root

    instance._touch_lock = threading.Lock()
    instance._last_touch = {}
    instance._touch_debounce_seconds = 15.0

    def write_retry(attempt, **_kwargs):
        with closing(connect()) as con:
            cur = attempt(con)
            con.commit()
            return cur

    instance._write_retry = write_retry
    assert instance.touch_if_registered(active_root) is True
    assert instance._next_cpu_project()["root"] == active_root


def test_touch_updates_only_matching_absolute_root(scheduler, tmp_path):
    instance, connect = scheduler
    now = instance._test_now[0]
    root_a = str(tmp_path / "project-a")
    root_b = str(tmp_path / "project-b")
    (tmp_path / "project-a").mkdir()
    (tmp_path / "project-b").mkdir()
    old = now - 86_401
    add(connect, root_a, "inventory", updated_at=now - 10, last_requested_at=old)
    add(connect, root_b, "inventory", updated_at=now - 10, last_requested_at=old)
    instance._touch_lock = threading.Lock()
    instance._last_touch = {}
    instance._touch_debounce_seconds = 15.0

    def write_retry(attempt, **_kwargs):
        with closing(connect()) as con:
            cur = attempt(con)
            con.commit()
            return cur

    instance._write_retry = write_retry

    assert instance.touch_if_registered(root_a) is True
    with closing(connect()) as con:
        rows = {str(row["root"]): float(row["last_requested_at"]) for row in con.execute(
            "SELECT root,last_requested_at FROM projects"
        )}
    assert rows[root_a] == now
    assert rows[root_b] == old


def test_background_step_does_not_refresh_foreground_activity(scheduler, tmp_path):
    instance, connect = scheduler
    root = str(tmp_path / "repo")
    (tmp_path / "repo").mkdir()
    now = instance._test_now[0]
    add(connect, root, "inventory", updated_at=now - 10, last_requested_at=now - 100)
    instance._background_work_allowed = lambda: True
    instance._yield = lambda: False
    instance._set_project = lambda *_args, **_kwargs: None
    instance._step_inventory = lambda _row: True
    instance.touch_if_registered = lambda _root: pytest.fail("background step refreshed foreground activity")

    assert instance._step({"root": root, "phase": "inventory", "status": "queued"}) is True

    with closing(connect()) as con:
        row = con.execute("SELECT last_requested_at FROM projects WHERE root=?", (root,)).fetchone()
    assert float(row[0]) == now - 100


def test_project_limit_bounds_candidates_and_does_not_skip_locked_head(scheduler):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "locked-head", "inventory", updated_at=now - 20, last_requested_at=now - 5)
    add(connect, "over-limit", "inventory", updated_at=now - 10, last_requested_at=now - 5)
    instance._rebalance_processing_slots = lambda _con, preferred_root=None: None
    instance._project_limit = lambda: 1
    lock = threading.Lock()
    lock.acquire()
    instance._step_locks_guard = threading.Lock()
    instance._step_locks = {"locked-head": lock}

    try:
        assert instance._next_cpu_project() is None
    finally:
        lock.release()


def test_stale_project_ages_ahead_of_new_active_work(scheduler):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "new-active", "inventory", updated_at=now - 10, last_requested_at=now - 5)
    add(connect, "aged-inactive", "modules", updated_at=now - 301, last_requested_at=now - 86_401)

    assert instance._next_cpu_project()["root"] == "aged-inactive"


def test_active_project_precedes_inactive_even_when_inactive_phase_is_earlier(scheduler):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "inactive-base", "inventory", updated_at=now - 20, last_requested_at=now - 86_401)
    add(connect, "active-optional", "modules", updated_at=now - 10, last_requested_at=now - 5)

    assert instance._next_cpu_project()["root"] == "active-optional"


def test_inactive_force_refresh_does_not_jump_active_layer(scheduler):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "inactive-forced", "inventory", updated_at=now - 20, last_requested_at=now - 86_401)
    add(connect, "active-normal", "modules", updated_at=now - 10, last_requested_at=now - 5)
    with closing(connect()) as con:
        con.execute("UPDATE projects SET force_refresh=1 WHERE root='inactive-forced'")
        con.commit()

    assert instance._next_cpu_project()["root"] == "active-normal"


def test_recent_foreground_activity_boosts_project_within_its_layer(scheduler):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "recently-used", "inventory", updated_at=now - 30, last_requested_at=now - 1)
    add(connect, "older-use", "inventory", updated_at=now - 10, last_requested_at=now - 120)

    assert instance._next_cpu_project()["root"] == "recently-used"


def test_scheduler_alternates_projects_after_durable_progress(scheduler):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "project-a", "hash", updated_at=now - 20, last_requested_at=now - 5)
    add(connect, "project-b", "hash", updated_at=now - 20, last_requested_at=now - 5)

    first = instance._next_cpu_project()
    assert first["root"] == "project-a"
    with closing(connect()) as con:
        con.execute("UPDATE projects SET updated_at=? WHERE root=?", (now, first["root"]))
        con.commit()

    assert instance._next_cpu_project()["root"] == "project-b"


def test_restart_resumes_from_persisted_phase(scheduler):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "resumed", "hash", updated_at=now - 10, last_requested_at=now - 5)

    resumed = ProjectPreprocessor.__new__(ProjectPreprocessor)
    resumed._connect = connect
    resumed._db_lock = threading.RLock()
    resumed._sqlite_write_retries = 1
    resumed.max_preprocessing_projects = 4

    row = resumed._next_cpu_project()
    assert row["root"] == "resumed"
    assert row["phase"] == "hash"


def test_retry_after_defers_phase_without_blocking_other_projects(scheduler):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "deferred", "inventory", updated_at=now - 30, last_requested_at=now - 5)
    add(connect, "ready", "hash", updated_at=now - 10, last_requested_at=now - 5)
    with closing(connect()) as con:
        con.execute("UPDATE projects SET retry_after=? WHERE root='deferred'", (now + 60,))
        con.commit()

    assert instance._next_cpu_project()["root"] == "ready"


def test_gpu_selector_respects_global_phase_order_and_files_precedes_modules(scheduler):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "modules", "modules", updated_at=now - 20, last_requested_at=now - 5)
    add(connect, "files", "files", updated_at=now - 10, last_requested_at=now - 5)

    assert instance._next_gpu_project()["root"] == "files"


@pytest.mark.parametrize(
    ("selector", "kwargs", "blocks_on_rebalance"),
    [
        ("_next_cpu_project", {"rebalance": True}, True),
        ("_next_cpu_project", {"rebalance": False}, False),
        ("_next_gpu_project", {}, True),
    ],
)
def test_scheduler_selector_serializes_rebalance_with_writer_actor(
    scheduler, selector, kwargs, blocks_on_rebalance
):
    instance, connect = scheduler
    now = instance._test_now[0]
    with closing(connect()) as con:
        initialize_wal(con)
    for index in range(5):
        add(connect, f"project-{index}", "inventory", updated_at=now - 10, last_requested_at=now - 5)

    actor = PreprocessWriteActor(instance.db_path, timeout_seconds=1)
    actor.start()
    actor_started = threading.Event()
    selector_started = threading.Event()
    release_actor = threading.Event()
    selector_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    writer_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        instance._write_actor = actor

        def connect_with_short_timeout():
            con = sqlite3.connect(actor.db_path, timeout=0.01)
            con.row_factory = sqlite3.Row
            return con

        def hold_writer_transaction(con):
            con.execute("UPDATE projects SET updated_at=updated_at WHERE root='project-0'")
            actor_started.set()
            release_actor.wait(2.0)

        instance._connect = connect_with_short_timeout
        blocker = writer_pool.submit(
            actor.submit,
            hold_writer_transaction,
        )
        assert actor_started.wait(1.0)

        def select_project():
            selector_started.set()
            return getattr(instance, selector)(**kwargs)

        selected = selector_pool.submit(select_project)
        assert selector_started.wait(1.0)
        time.sleep(0.05)
        if blocks_on_rebalance:
            if selected.done():
                selected.result()
            assert not selected.done()
        else:
            assert selected.result(timeout=0.5)["root"].startswith("project-")

        release_actor.set()
        blocker.result(timeout=1.0)
        if blocks_on_rebalance:
            selected.result(timeout=1.0)
    finally:
        release_actor.set()
        actor.stop()
        selector_pool.shutdown(wait=True)
        writer_pool.shutdown(wait=True)
