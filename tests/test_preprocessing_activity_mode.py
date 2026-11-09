from local_ai_hub.operational_mode import (
    load_operational_mode,
    operational_mode_gate_error,
    publish_preprocessing_ready,
    set_operational_mode,
)


def test_preprocessing_mode_persists_blocks_requests_and_can_be_exited(tmp_path):
    selected = set_operational_mode(tmp_path, "preprocessing")
    assert load_operational_mode(tmp_path) == selected
    for heavy in (False, True):
        result = operational_mode_gate_error(selected, "search", requires_heavy_work=heavy)
        assert result["mode"] == "preprocessing"
        assert result["retryable"] is True
    active = set_operational_mode(tmp_path, "active")
    assert operational_mode_gate_error(active, "search") is None


def test_preprocessing_mode_blocks_mcp_repository_requests_before_dispatch(tmp_path, monkeypatch):
    import asyncio
    from local_ai_hub import mcp_server

    selected = set_operational_mode(tmp_path, "preprocessing")
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda *_args: selected)
    calls = []
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *args, **kwargs: calls.append((args, kwargs)))
    result = asyncio.run(mcp_server._compact_mcp_call_tool(
        "local_ai_repo", {"action": "search", "root": str(tmp_path), "query": "example"}
    ))[1]
    assert result["success"] is False
    assert result["mode"] == "preprocessing"
    assert result["retryable"] is True
    assert calls == []

    monkeypatch.setattr(mcp_server.FEATURES, "status", True)
    monkeypatch.setattr(mcp_server.CLIENT, "get", lambda *args, **kwargs: {"hub_online": True})
    status = asyncio.run(mcp_server._compact_mcp_call_tool("local_ai_status", {}))[1]
    assert status["success"] is True


def test_preprocessing_mode_allows_preprocessing_steps(tmp_path):
    from local_ai_hub.preprocess import ProjectPreprocessor

    processor = object.__new__(ProjectPreprocessor)
    processor.enabled = True
    processor.state_dir = tmp_path
    selected = set_operational_mode(tmp_path, "preprocessing")
    assert not processor._background_work_allowed()
    publish_preprocessing_ready(tmp_path, selected)
    assert processor._background_work_allowed()
    newer = set_operational_mode(tmp_path, "preprocessing")
    assert not processor._background_work_allowed()
    try:
        publish_preprocessing_ready(tmp_path, selected)
    except ValueError:
        pass
    else:
        raise AssertionError("stale mode revision was published")
    publish_preprocessing_ready(tmp_path, newer)
    assert processor._background_work_allowed()


def test_preprocessing_mode_admits_own_generation_after_foreground_drains(tmp_path):
    from types import SimpleNamespace
    from local_ai_hub.preprocess import ProjectPreprocessor

    calls = []
    processor = object.__new__(ProjectPreprocessor)
    processor.state_dir = tmp_path
    processor.config = {}
    processor.background_gpu = SimpleNamespace(generate=lambda **kw: calls.append(kw) or {"success": True})
    processor._gpu_yield = lambda: False
    selected = set_operational_mode(tmp_path, "preprocessing")
    assert processor._run_background_generate("model", "prompt", "system", {}, 32, "preprocess-file")["success"] is False
    publish_preprocessing_ready(tmp_path, selected)
    result = processor._run_background_generate("model", "prompt", "system", {}, 32, "preprocess-file")
    assert result["success"] is True
    assert calls[0]["preprocessing"] is True

    processor._gpu_yield = lambda: True
    assert processor._run_background_generate("model", "prompt", "system", {}, 32, "preprocess-file")["preempted"]
    assert len(calls) == 1


def test_async_job_gate_preserves_preprocessing_mode_identity(tmp_path):
    from local_ai_hub.async_jobs import AsyncJobManager

    snapshot = set_operational_mode(tmp_path, "preprocessing")
    normalized = AsyncJobManager._normalize_operational_mode_snapshot(snapshot, operational_mode_gate_error)
    assert normalized["mode"] == "preprocessing"
    assert normalized["degraded"] is False


def test_scheduler_skips_project_already_owned_by_another_worker(tmp_path):
    import sqlite3
    import threading
    from contextlib import closing
    from local_ai_hub.preprocess import ProjectPreprocessor

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
        con.executemany("INSERT INTO projects(root,status,phase,updated_at) VALUES(?,?,?,?)",
                        [("first", "running", "hash", 1), ("second", "running", "hash", 2)])
        con.commit()
    processor = object.__new__(ProjectPreprocessor)
    processor._connect = connect
    processor._db_lock = threading.RLock()
    processor._step_locks_guard = threading.Lock()
    processor._step_locks = {}
    processor.max_preprocessing_projects = 2
    processor._watcher_active = True
    lock = processor._project_step_lock("first")
    with lock:
        assert processor._next_cpu_project()["root"] == "second"
        with closing(connect()) as con:
            con.execute("UPDATE projects SET phase='files'")
            con.commit()
        assert processor._next_gpu_project()["root"] == "second"


def test_rebalance_keeps_a_running_project_until_its_step_finishes(tmp_path):
    import sqlite3
    import threading
    import time
    from contextlib import closing
    from local_ai_hub.preprocess import ProjectPreprocessor

    db = tmp_path / "projects.sqlite"
    def connect():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        return con
    with closing(connect()) as con:
        con.execute("""CREATE TABLE projects (root TEXT PRIMARY KEY, status TEXT, phase TEXT,
            paused INTEGER DEFAULT 0, updated_at REAL, force_refresh INTEGER DEFAULT 0,
            last_requested_at REAL DEFAULT 0, retry_after REAL DEFAULT 0)""")
        now = time.time()
        con.executemany("INSERT INTO projects(root,status,phase,updated_at) VALUES(?,?,?,?)",
                        [("working", "running", "hash", now), ("waiting", "waiting", "hash", now)])
        con.commit()
        processor = object.__new__(ProjectPreprocessor)
        processor.max_preprocessing_projects = 1
        processor._step_locks_guard = threading.Lock()
        processor._step_locks = {}
        with processor._project_step_lock("working"):
            processor._rebalance_processing_slots(con, preferred_root="waiting")
            rows = {row["root"]: row["status"] for row in con.execute("SELECT root,status FROM projects")}
            assert rows == {"working": "running", "waiting": "waiting"}
            con.execute("UPDATE projects SET status='running' WHERE root='waiting'")
            with processor._project_step_lock("waiting"):
                processor._rebalance_processing_slots(con)
                rows = {row["root"]: row["status"] for row in con.execute("SELECT root,status FROM projects")}
                assert rows == {"working": "running", "waiting": "running"}


def test_worker_rechecks_admission_after_selection():
    import threading
    from local_ai_hub.preprocess import ProjectPreprocessor

    processor = object.__new__(ProjectPreprocessor)
    processor._paused = threading.Event()
    processor._background_work_allowed = lambda: True
    processor._step_locks_guard = threading.Lock()
    processor._step_locks = {}
    processor._stats_lock = threading.Lock()
    processor._stats = {"project_step_contention": 0}
    processor._project_row = lambda root: {"root": root, "status": "waiting", "phase": "hash", "paused": 0}
    processor._step = lambda row: (_ for _ in ()).throw(AssertionError("stale row was executed"))
    assert processor._run_project_step({"root": "project", "status": "queued", "phase": "hash"}) is None


def test_background_executor_only_admits_preprocessing_in_preprocessing_mode(tmp_path):
    from types import SimpleNamespace
    from local_ai_hub.background_gpu import IdleGPUWorker

    class Profile:
        prompt_budget_tokens = 8192
        def cache_scope(self):
            return "test"

    class Policy:
        def profile(self, *args, **kwargs):
            return Profile()
        def apply_payload(self, model, payload, **kwargs):
            return payload, Profile()

    calls = []
    runtime = SimpleNamespace(request_interruptible=lambda *args, **kwargs: calls.append(args) or {"response": "{}"})
    worker = object.__new__(IdleGPUWorker)
    worker.config = {"server": {"state_dir": str(tmp_path)}}
    worker.model = "model"
    worker.request_timeout = 1
    worker._bg_config = {"ollama": {}}
    worker.runtime = runtime
    worker.policy = Policy()
    task = {"prompt": "hello", "system": "", "schema": {}, "max_tokens": 32}
    selected = set_operational_mode(tmp_path, "preprocessing")
    assert worker._generate_one(task, preemptible=False)["error_code"] == "operational_mode_paused"
    assert worker._generate_one(task, preemptible=False, preprocessing=True)["error_code"] == "operational_mode_paused"
    publish_preprocessing_ready(tmp_path, selected)
    assert worker._generate_one(task, preemptible=False, preprocessing=True)["success"] is True
    assert len(calls) == 1
    set_operational_mode(tmp_path, "gaming")
    assert worker._generate_one(task, preemptible=False, preprocessing=True)["error_code"] == "operational_mode_paused"
    assert len(calls) == 1


def test_each_hardware_profile_defines_exclusive_preprocessing_limits():
    from local_ai_hub.hardware import profile_overrides

    profiles = ("cpu", "integrated", "low", "balanced", "medium", "high", "max")
    limits = [profile_overrides(profile)["preprocessing"]["exclusive"] for profile in profiles]
    for item in limits:
        assert set(item) == {"max_projects", "cpu_workers", "model_parallel"}
        assert all(type(value) is int and value > 0 for value in item.values())
    assert limits[-1]["max_projects"] > limits[0]["max_projects"]


def test_each_profile_resolves_and_restores_user_overridden_project_limit(tmp_path, monkeypatch):
    from local_ai_hub import hardware
    from local_ai_hub.config import load_config
    from local_ai_hub.preprocess import ProjectPreprocessor

    for profile in ("cpu", "integrated", "low", "balanced", "medium", "high", "max"):
        monkeypatch.setattr(hardware, "detect_hardware", lambda _profile: {"profile": profile})
        state = tmp_path / profile
        path = tmp_path / f"{profile}.toml"
        path.write_text(
            f'[server]\nstate_dir = "{state.as_posix()}"\n'
            f'[hardware]\nprofile = "{profile}"\n'
            '[preprocessing.exclusive]\nmax_projects = 7\nmodel_parallel = 3\n',
            encoding="utf-8",
        )
        config = load_config(path)
        exclusive = config["preprocessing"]["exclusive"]
        assert exclusive["max_projects"] == 7
        assert exclusive["model_parallel"] == 3
        assert exclusive["cpu_workers"] == hardware.profile_overrides(profile)["preprocessing"]["exclusive"]["cpu_workers"]
        processor = object.__new__(ProjectPreprocessor)
        processor.state_dir = state
        processor.max_preprocessing_projects = config["preprocessing"]["max_preprocessing_projects"]
        processor.exclusive_max_projects = exclusive["max_projects"]
        assert processor._project_limit() == processor.max_preprocessing_projects
        set_operational_mode(state, "preprocessing")
        assert processor._project_limit() == 7
        set_operational_mode(state, "active")
        assert processor._project_limit() == processor.max_preprocessing_projects


def test_project_limit_tracks_mode_and_restores_normal_value(tmp_path):
    from local_ai_hub.preprocess import ProjectPreprocessor

    processor = object.__new__(ProjectPreprocessor)
    processor.state_dir = tmp_path
    processor.max_preprocessing_projects = 2
    processor.exclusive_max_projects = 6
    assert processor._project_limit() == 2
    set_operational_mode(tmp_path, "preprocessing")
    assert processor._project_limit() == 6
    set_operational_mode(tmp_path, "active")
    assert processor._project_limit() == 2


def test_real_worker_pool_uses_mode_limit_and_cpu_capacity(tmp_path, monkeypatch):
    from local_ai_hub import preprocess

    monkeypatch.setattr(preprocess.os, "cpu_count", lambda: 12)
    config = {
        "server": {"state_dir": str(tmp_path)},
        "preprocessing": {
            "enabled": False, "cpu_workers": 3, "max_preprocessing_projects": 2,
            "exclusive": {"cpu_workers": 48, "max_projects": 8},
        },
    }
    worker = preprocess.ProjectPreprocessor(config, None, None, None, None, None)
    try:
        assert worker._hash_pool()._max_workers == 3
        assert worker._project_limit() == 2
        set_operational_mode(tmp_path, "preprocessing")
        assert worker._hash_pool()._max_workers == 12
        assert worker._project_limit() == 8
        set_operational_mode(tmp_path, "active")
        assert worker._hash_pool()._max_workers == 3
        assert worker._project_limit() == 2
    finally:
        worker.close()


def test_extra_project_workers_only_run_in_preprocessing_mode(tmp_path):
    import threading
    from types import SimpleNamespace
    from local_ai_hub.preprocess import ProjectPreprocessor

    processor = object.__new__(ProjectPreprocessor)
    processor.state_dir = tmp_path
    processor.enabled = True
    processor.cfg = {"startup_delay_seconds": 0, "poll_seconds": 0.2, "fs_watcher_enabled": False}
    processor.cpu_priority = "idle"
    processor.cpu_runs_during_foreground = True
    processor.exclusive_max_projects = 2
    processor._stop = threading.Event()
    processor._paused = threading.Event()
    processor._cpu_wakeup = threading.Event()
    processor._gpu_wakeup = threading.Event()
    processor._stats_lock = threading.Lock()
    processor._stats = {"loops": 0, "steps": 0, "yields": 0, "errors": 0}
    processor._cpu_thread = processor._gpu_thread = processor._fs_watcher_thread = None
    processor._extra_cpu_threads = []
    processor._cpu_pool = SimpleNamespace(shutdown=lambda **kwargs: None)
    processor._gpu_loop = lambda: None
    processor._background_work_allowed = lambda: True
    processor._mark_step_recovered = lambda root: None
    processor._run_idle_database_maintenance = lambda: None
    pending = [{"root": "a"}, {"root": "b"}]
    lock = threading.Lock()
    first, second, release = threading.Event(), threading.Event(), threading.Event()
    def next_project():
        with lock:
            return pending.pop(0) if pending else None
    def step(row, **_kwargs):
        (first if row["root"] == "a" else second).set()
        release.wait(4)
        return True
    processor._next_cpu_project = next_project
    processor._run_project_step = step
    try:
        processor.ensure_running()
        assert first.wait(2)
        assert not second.wait(0.4)
        set_operational_mode(tmp_path, "preprocessing")
        processor._wake_all()
        assert second.wait(2)
    finally:
        release.set()
        processor.close()


def test_hash_pool_switches_with_activity_mode(tmp_path):
    from local_ai_hub.preprocess import ProjectPreprocessor

    processor = object.__new__(ProjectPreprocessor)
    processor.state_dir = tmp_path
    normal, exclusive = object(), object()
    processor._cpu_pool = normal
    processor._exclusive_cpu_pool = exclusive
    assert processor._hash_pool() is normal
    set_operational_mode(tmp_path, "preprocessing")
    assert processor._hash_pool() is exclusive
    set_operational_mode(tmp_path, "active")
    assert processor._hash_pool() is normal


def test_gpu_worker_skips_idle_grace_only_in_preprocessing_mode(tmp_path):
    import threading
    from local_ai_hub.background_gpu import IdleGPUWorker

    class Scheduler:
        busy = False
        def foreground_busy(self):
            return self.busy
        def foreground_idle_seconds(self):
            return 1

    worker = object.__new__(IdleGPUWorker)
    worker.config = {"server": {"state_dir": str(tmp_path)}}
    worker.enabled = True
    worker.model = "model"
    worker._startup_circuit_open = worker._stop_unconfirmed = False
    worker.scheduler = Scheduler()
    worker._lock = threading.Lock()
    worker._retry_after = 0
    worker._lease = False
    worker.idle_seconds = 60
    assert not worker.ready()
    selected = set_operational_mode(tmp_path, "preprocessing")
    assert not worker.ready()
    publish_preprocessing_ready(tmp_path, selected)
    assert worker.ready()
    worker.scheduler.busy = True
    assert not worker.ready()


def test_exclusive_cpu_work_skips_grace_but_not_foreground_fence(tmp_path):
    from types import SimpleNamespace
    from local_ai_hub.preprocess import ProjectPreprocessor

    busy = [False]
    processor = object.__new__(ProjectPreprocessor)
    processor.state_dir = tmp_path
    processor.scheduler = SimpleNamespace(background_allowed=lambda: False, foreground_busy=lambda: busy[0])
    assert not processor._scheduler_background_allowed()
    selected = set_operational_mode(tmp_path, "preprocessing")
    assert not processor._scheduler_background_allowed()
    publish_preprocessing_ready(tmp_path, selected)
    assert processor._scheduler_background_allowed()
    busy[0] = True
    assert not processor._scheduler_background_allowed()


def test_cpu_fallback_is_ready_in_confirmed_preprocessing_mode(tmp_path):
    import threading
    from types import SimpleNamespace
    from local_ai_hub.background_gpu import IdleGPUWorker
    from local_ai_hub.hardware import profile_overrides

    assert profile_overrides("cpu")["background_gpu"]["cpu_fallback_enabled"] is True
    worker = object.__new__(IdleGPUWorker)
    worker.config = {"server": {"state_dir": str(tmp_path)}}
    worker.enabled = False
    worker.cpu_fallback_enabled = True
    worker.model = "model"
    worker._startup_circuit_open = worker._stop_unconfirmed = False
    worker.scheduler = SimpleNamespace(foreground_busy=lambda: False, foreground_idle_seconds=lambda: 0)
    worker._lock = threading.RLock()
    worker._retry_after = 0
    worker._lease = False
    worker.idle_seconds = 60
    assert not worker.ready()
    selected = set_operational_mode(tmp_path, "preprocessing")
    assert not worker.ready()
    publish_preprocessing_ready(tmp_path, selected)
    assert worker.ready()
    worker.cpu_fallback_enabled = False
    assert not worker.ready()


def test_exclusive_config_overrides_selected_profile(tmp_path, monkeypatch):
    from local_ai_hub import hardware
    from local_ai_hub.config import load_config

    monkeypatch.setattr(hardware, "detect_hardware", lambda profile: {"profile": "high"})
    path = tmp_path / "config.toml"
    path.write_text(
        f'[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\n'
        '[hardware]\nprofile = "high"\n'
        '[preprocessing.exclusive]\nmax_projects = 4\ncpu_workers = 5\nmodel_parallel = 2\n',
        encoding="utf-8",
    )
    config = load_config(path)
    assert config["preprocessing"]["exclusive"] == {
        "max_projects": 4, "cpu_workers": 5, "model_parallel": 2, "enrich_stub_cards": True,
    }


def test_model_parallelism_changes_only_after_inflight_work_drains(tmp_path, monkeypatch):
    import threading
    from types import SimpleNamespace
    from local_ai_hub import background_gpu

    stopped = []
    class Pool:
        def __init__(self, max_workers, **kwargs):
            self.max_workers = max_workers
        def shutdown(self, **kwargs):
            stopped.append("pool")
    monkeypatch.setattr(background_gpu, "ThreadPoolExecutor", Pool)
    monkeypatch.setattr(background_gpu, "OllamaRuntime", lambda cfg, **kwargs: SimpleNamespace(config=cfg))
    monkeypatch.setattr(background_gpu, "ModelExecutionPolicy", lambda cfg: SimpleNamespace(config=cfg))
    worker = object.__new__(background_gpu.IdleGPUWorker)
    worker.config = {"server": {"state_dir": str(tmp_path)}}
    worker._bg_config = {"server": {}, "scheduler": {}, "ollama": {}, "model_execution": {"background": {}}}
    worker.cfg = {}
    worker.parallel = worker._normal_parallel = 2
    worker._exclusive_parallel = 6
    worker._lock = threading.RLock()
    worker._active = 1
    worker._lease = True
    worker._stop_unconfirmed = False
    worker._executor = Pool(2)
    def stop():
        stopped.append("server")
        worker._lease = False
        return True
    worker._stop_and_release_gpu = stop
    selected = set_operational_mode(tmp_path, "preprocessing")
    publish_preprocessing_ready(tmp_path, selected)
    assert worker._configure_parallel_for_mode() is False
    assert worker.parallel == 2 and stopped == []
    worker._active = 0
    worker._stop_and_release_gpu = lambda: False
    assert worker._configure_parallel_for_mode() is False
    assert worker.parallel == 2
    assert worker._executor.max_workers == 2
    stopped.clear()
    worker._stop_and_release_gpu = stop
    assert worker._configure_parallel_for_mode() is True
    assert worker.parallel == 6
    assert worker._bg_config["ollama"]["num_parallel"] == 6
    assert worker._executor.max_workers == 6
    assert stopped == ["server", "pool"]
    set_operational_mode(tmp_path, "active")
    assert worker._configure_parallel_for_mode() is True
    assert worker.parallel == worker._bg_config["ollama"]["num_parallel"] == 2


def test_batch_defers_when_model_profile_cannot_safely_change():
    import threading
    from local_ai_hub.background_gpu import IdleGPUWorker

    worker = object.__new__(IdleGPUWorker)
    worker._setup_lock = threading.RLock()
    worker._configure_parallel_for_mode = lambda: False
    worker._acquire_session = lambda: (_ for _ in ()).throw(AssertionError("session started during transition"))
    result = worker.generate_many([{"prompt": "work"}], preprocessing=True)
    assert result[0]["success"] is False
    assert result[0]["idle_wait"] is True


def test_model_profile_waits_for_real_inflight_batch(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace
    from local_ai_hub import background_gpu

    monkeypatch.setattr(background_gpu, "OllamaRuntime", lambda cfg, **kwargs: SimpleNamespace(config=cfg))
    monkeypatch.setattr(background_gpu, "ModelExecutionPolicy", lambda cfg: SimpleNamespace(config=cfg))
    worker = object.__new__(background_gpu.IdleGPUWorker)
    worker._idle_release_timer = None
    worker._schedule_idle_release = lambda: None
    worker.config = {"server": {"state_dir": str(tmp_path)}}
    worker.cfg = {}
    worker._bg_config = {"server": {}, "scheduler": {}, "ollama": {}, "model_execution": {"background": {}}}
    worker.parallel = worker._normal_parallel = 1
    worker._exclusive_parallel = 3
    worker._setup_lock, worker._lock = threading.RLock(), threading.RLock()
    worker._active = 0
    worker._lease, worker._stop_unconfirmed = True, False
    worker._stats = {"batches": 0, "submitted": 0, "completed": 0, "failed": 0}
    worker._executor = ThreadPoolExecutor(max_workers=1)
    worker.runtime, worker.policy = object(), object()
    worker._acquire_session = lambda: True
    worker._foreground_requested = lambda: False
    worker._stop_and_release_gpu = lambda: setattr(worker, "_lease", False) or True
    started, release = threading.Event(), threading.Event()
    def generate(*args, **kwargs):
        started.set()
        release.wait(5)
        return {"success": True}
    worker._generate_one = generate
    output = []
    thread = threading.Thread(target=lambda: output.extend(worker.generate_many([{}], preprocessing=True)))
    try:
        thread.start()
        assert started.wait(2)
        selected = set_operational_mode(tmp_path, "preprocessing")
        publish_preprocessing_ready(tmp_path, selected)
        pending = worker.generate_many([{}], preprocessing=True)
        assert pending[0]["idle_wait"] is True
        assert worker.parallel == 1
        release.set()
        thread.join(3)
        assert not thread.is_alive() and output == [{"success": True}]
        assert worker.generate_many([{}], preprocessing=True)[0]["success"] is True
        assert worker.parallel == 3
        barrier = threading.Barrier(3, timeout=2)
        def concurrent_generation(*args, **kwargs):
            barrier.wait()
            return {"success": True}
        worker._generate_one = concurrent_generation
        assert all(result["success"] for result in worker.generate_many([{}, {}, {}], preprocessing=True))
        exit_started, exit_release = threading.Event(), threading.Event()
        exit_output = []
        def drain_during_exit(*args, **kwargs):
            exit_started.set()
            exit_release.wait(5)
            return {"success": True}
        worker._generate_one = drain_during_exit
        exit_thread = threading.Thread(
            target=lambda: exit_output.extend(worker.generate_many([{}], preprocessing=True))
        )
        try:
            exit_thread.start()
            assert exit_started.wait(2)
            set_operational_mode(tmp_path, "active")
            pending = worker.generate_many([{}], preprocessing=True)
            assert pending[0]["idle_wait"] is True
            assert worker.parallel == 3
            exit_release.set()
            exit_thread.join(3)
            assert not exit_thread.is_alive() and exit_output == [{"success": True}]
        finally:
            exit_release.set()
            exit_thread.join(3)
        worker._generate_one = lambda *args, **kwargs: {"success": True}
        assert worker.generate_many([{}], preprocessing=True)[0]["success"] is True
        assert worker.parallel == 1
    finally:
        release.set()
        thread.join(3)
        worker._executor.shutdown(wait=True)


def test_cpu_fallback_serializes_concurrent_project_batches(tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from local_ai_hub.background_gpu import IdleGPUWorker

    worker = object.__new__(IdleGPUWorker)
    worker._idle_release_timer = None
    worker._schedule_idle_release = lambda: None
    worker.config = {"server": {"state_dir": str(tmp_path)}}
    worker._setup_lock, worker._lock, worker._cpu_slot = threading.RLock(), threading.RLock(), threading.Lock()
    worker._configure_parallel_for_mode = lambda: True
    worker._acquire_session = lambda: False
    acquisitions = []
    worker._acquire_cpu_session = lambda: acquisitions.append(True) or True
    worker.parallel, worker._active = 4, 0
    worker._stats = {"batches": 0, "submitted": 0, "completed": 0, "failed": 0}
    worker._executor = ThreadPoolExecutor(max_workers=4)
    worker.cpu_runtime = worker.cpu_policy = object()
    worker._cpu_config = {"server": {}}
    started, release = threading.Event(), threading.Event()
    def generate(*args, **kwargs):
        started.set()
        release.wait(5)
        return {"success": True}
    worker._generate_one = generate
    output = []
    thread = threading.Thread(target=lambda: output.extend(worker.generate_many([{}], preprocessing=True)))
    try:
        thread.start()
        assert started.wait(2)
        pending = worker.generate_many([{}], preprocessing=True)
        assert pending[0]["idle_wait"] is True
        assert len(acquisitions) == 1
        release.set()
        thread.join(3)
        assert output == [{"success": True}]
    finally:
        release.set()
        thread.join(3)
        worker._executor.shutdown(wait=True)


def test_cpu_fallback_start_failure_has_bounded_retry_interval():
    import threading
    from types import SimpleNamespace
    from local_ai_hub.background_gpu import IdleGPUWorker

    worker = object.__new__(IdleGPUWorker)
    worker._closed = False
    worker.cpu_fallback_enabled = True
    worker.model = "model"
    worker._setup_lock, worker._lock = threading.RLock(), threading.RLock()
    worker._cpu_retry_after = 0.0
    worker._cpu_retry_interval = 60.0
    worker._cpu_lease = False
    attempts = []
    worker.cpu_runtime = SimpleNamespace(is_online=lambda: False, ensure_running=lambda: attempts.append(True) or False)
    assert not worker._acquire_cpu_session()
    assert not worker._acquire_cpu_session()
    assert len(attempts) == 1


def test_cpu_fallback_profile_probe_failure_is_reported_and_deferred():
    import threading
    from types import SimpleNamespace
    from local_ai_hub.background_gpu import IdleGPUWorker

    worker = object.__new__(IdleGPUWorker)
    worker._closed = False
    worker.cpu_fallback_enabled = True
    worker.model = "model"
    worker._setup_lock, worker._lock = threading.RLock(), threading.RLock()
    worker._cpu_retry_after = 0.0
    worker._cpu_retry_interval = 60.0
    worker._cpu_lease = False
    worker.cpu_runtime = SimpleNamespace(is_online=lambda: False, ensure_running=lambda: True,
                                         managed_profile_status=lambda: (_ for _ in ()).throw(RuntimeError("probe")))
    assert worker._acquire_cpu_session() is False
    assert worker._cpu_retry_after > 0


def test_background_worker_uses_configured_preprocessing_model(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from local_ai_hub import background_gpu

    monkeypatch.setattr(background_gpu, "OllamaRuntime", lambda cfg, **kwargs: SimpleNamespace(config=cfg))
    monkeypatch.setattr(background_gpu, "ModelExecutionPolicy", lambda cfg: SimpleNamespace(config=cfg))
    config = {
        "server": {"state_dir": str(tmp_path)},
        "models": {"background_code": "other-model"},
        "preprocessing": {"model": "configured-preprocessing-model"},
    }
    worker = background_gpu.IdleGPUWorker(config, foreground_scheduler=object())
    try:
        assert worker.model == "configured-preprocessing-model"
    finally:
        worker._executor.shutdown(wait=True)


def test_module_cards_use_preprocessing_admission():
    import threading
    from types import SimpleNamespace
    from local_ai_hub.preprocess import ProjectPreprocessor

    calls, stored = [], []
    processor = object.__new__(ProjectPreprocessor)
    processor.config = {"preprocessing": {"model": "configured"}, "background_gpu": {}}
    processor.cfg = {"prefer_deterministic_modules": False}
    processor.deterministic = None
    processor._stats_lock = threading.Lock()
    processor._stats = {"module_generations": 0}
    processor._modules_needing_card = lambda root: [("module", "revision", [{"path": "a.py", "card": {}}])]
    processor._store_module_card = lambda *args: stored.append(args)
    processor._generated_card_data = lambda result: result["data"]
    processor.background_gpu = SimpleNamespace(
        ready=lambda: True,
        generate_many=lambda tasks, **kw: calls.append(kw) or [{"success": True, "data": {}}],
    )
    assert processor._step_module({"root": "project"}) is True
    assert calls == [{"preprocessing": True}]
    assert len(stored) == 1


def test_dashboard_exposes_preprocessing_activity_mode():
    from local_ai_hub.dashboard import DASHBOARD_HTML

    assert 'data-activity-mode="preprocessing"' in DASHBOARD_HTML
    assert "'preprocessing'" in DASHBOARD_HTML[DASHBOARD_HTML.index("const ACTIVITY_MODES="):][:100]
    assert "preprocessing:'Preprocessing'" in DASHBOARD_HTML
    assert "data.preprocessing_ready!==true" in DASHBOARD_HTML
    assert "Preprocessing not ready. Select Preprocessing to retry." in DASHBOARD_HTML


def test_exclusive_entry_rechecks_complete_projects_without_discarding_cache(tmp_path):
    import sqlite3
    import threading
    from contextlib import closing
    from local_ai_hub.preprocess import ProjectPreprocessor

    db = tmp_path / "projects.sqlite"
    def connect():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        return con
    with closing(connect()) as con:
        con.execute("""CREATE TABLE projects (root TEXT PRIMARY KEY, status TEXT, phase TEXT,
            paused INTEGER DEFAULT 0, updated_at REAL DEFAULT 0, force_refresh INTEGER DEFAULT 0,
            last_requested_at REAL DEFAULT 0, retry_after REAL DEFAULT 0, next_check_at REAL DEFAULT 0)""")
        con.executemany("INSERT INTO projects(root,status,phase) VALUES(?,?,?)",
                        [("done", "complete", "complete"), ("working", "running", "hash")])
        con.commit()
    processor = object.__new__(ProjectPreprocessor)
    processor.state_dir = tmp_path
    processor.max_preprocessing_projects = 2
    processor.enabled = True
    processor._step_locks_guard = threading.Lock()
    processor._step_locks = {}
    processor.resume = lambda: {"success": True}
    processor._wake_all = lambda: None
    processor.status = lambda: {"success": True}
    def write(fn):
        with closing(connect()) as con:
            fn(con)
            con.commit()
    processor._write_retry = write
    assert processor.start_exclusive()["success"] is True
    with closing(connect()) as con:
        rows = {row["root"]: (row["phase"], row["force_refresh"]) for row in con.execute("SELECT * FROM projects")}
    assert rows == {"done": ("inventory", 0), "working": ("hash", 0)}
    processor.enabled = False
    assert processor.start_exclusive()["success"] is False
