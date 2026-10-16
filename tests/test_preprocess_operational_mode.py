import json
import sys
import threading
import types
from pathlib import Path
from types import SimpleNamespace

from local_ai_hub.preprocess import ProjectPreprocessor
import pytest
from local_ai_hub import preprocess as preprocess_module
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.operational_mode import set_operational_mode
from local_ai_hub.repo_tools import RepositoryTools


def _preprocessor(state_dir: Path) -> ProjectPreprocessor:
    pre = object.__new__(ProjectPreprocessor)
    pre.state_dir = state_dir
    pre.cpu_runs_during_foreground = True
    pre.cfg = {"poll_seconds": 0.2}
    pre.cpu_priority = "idle"
    pre._paused = threading.Event()
    pre._stop = threading.Event()
    pre._cpu_wakeup = threading.Event()
    pre._stats_lock = threading.Lock()
    pre._stats = {"loops": 0}
    pre._set_project = lambda *_args, **_kwargs: None
    return pre


def _set_mode(state_dir: Path, mode: str) -> None:
    (state_dir / "operational_mode.json").write_text(
        json.dumps({"mode": mode, "revision": 1, "updated_at": "now"}),
        encoding="utf-8",
    )


def test_gaming_finishes_current_step_then_active_resumes_one_checkpoint(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    pre = _preprocessor(tmp_path / "state")
    pre.state_dir.mkdir(exist_ok=True)
    steps: list[str] = []

    def finish_current_step(_row: dict[str, object]) -> bool:
        steps.append("inventory")
        _set_mode(pre.state_dir, "gaming")
        return True

    pre._step_inventory = finish_current_step

    row = {"root": str(root), "phase": "inventory"}
    _set_mode(pre.state_dir, "active")
    assert pre._step(row) is True
    assert steps == ["inventory"]

    # Mode changes do not interrupt an in-flight bounded step, but block next one.
    assert pre._step(row) is False
    assert steps == ["inventory"]

    _set_mode(pre.state_dir, "active")
    assert pre._step(row) is True
    assert steps == ["inventory", "inventory"]


def test_gaming_cpu_loop_does_not_schedule_another_project_step(tmp_path: Path) -> None:
    pre = _preprocessor(tmp_path)
    pre.state_dir.mkdir(exist_ok=True)
    _set_mode(pre.state_dir, "gaming")
    selected: list[bool] = []
    pre._next_cpu_project = lambda: selected.append(True)

    class StopOnWait:
        def wait(self, _timeout: float) -> None:
            pre._stop.set()

        def clear(self) -> None:
            pass

    pre._cpu_wakeup = StopOnWait()
    pre._cpu_loop()
    assert selected == []


def test_gaming_gpu_loop_does_not_schedule_another_project_step(tmp_path: Path) -> None:
    pre = _preprocessor(tmp_path)
    pre.state_dir.mkdir(exist_ok=True)
    _set_mode(pre.state_dir, "gaming")
    selected: list[bool] = []
    pre._next_gpu_project = lambda: selected.append(True)

    class StopOnWait:
        def wait(self, _timeout: float) -> None:
            pre._stop.set()

        def clear(self) -> None:
            pass

    pre._gpu_wakeup = StopOnWait()
    pre._gpu_loop()
    assert selected == []


def test_gaming_unschedules_watcher_and_active_resyncs_once(
    tmp_path: Path, monkeypatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    pre = _preprocessor(tmp_path)
    pre.state_dir.mkdir(exist_ok=True)
    pre._db_lock = threading.RLock()
    pre._dirty_lock = threading.RLock()
    pre._dirty_paths = {}
    pre._watch_revisions = {}
    pre._watcher_active = False
    pre._stats["watcher_errors"] = 0

    class Cursor:
        def fetchall(self):
            return [(str(root),)]

    class Connection:
        def execute(self, _sql):
            return Cursor()

        def close(self):
            pass

    pre._connect = lambda: Connection()

    class Observer:
        def __init__(self):
            self.starts = 0
            self.stops = 0
            self.joins = 0
            self.scheduled = []
            self.unscheduled = []

        def start(self):
            self.starts += 1

        def schedule(self, handler, watched_root, recursive):
            handle = object()
            self.scheduled.append((handle, handler, watched_root, recursive))
            return handle

        def unschedule(self, handle):
            self.unscheduled.append(handle)
            if len(self.unscheduled) == 1:
                _, handler, watched_root, _ = self.scheduled[0]
                handler.on_any_event(SimpleNamespace(
                    event_type="modified",
                    is_directory=False,
                    src_path=str(Path(watched_root) / "late.py"),
                    dest_path="",
                ))

        def stop(self):
            self.stops += 1

        def join(self, timeout):
            self.joins += 1

    observer = Observer()
    observers_module = types.ModuleType("watchdog.observers")
    observers_module.Observer = lambda: observer
    events_module = types.ModuleType("watchdog.events")
    events_module.FileSystemEventHandler = type("FileSystemEventHandler", (), {})
    watchdog_module = types.ModuleType("watchdog")
    watchdog_module.__path__ = []
    monkeypatch.setitem(sys.modules, "watchdog", watchdog_module)
    monkeypatch.setitem(sys.modules, "watchdog.observers", observers_module)
    monkeypatch.setitem(sys.modules, "watchdog.events", events_module)

    class ModeTransitions:
        waits = 0
        stopped = False

        def is_set(self):
            return self.stopped

        def wait(self, _timeout):
            self.waits += 1
            if self.waits in {1, 2, 4}:
                _set_mode(pre.state_dir, "active")
            elif self.waits == 3:
                _set_mode(pre.state_dir, "gaming")
            else:
                self.stopped = True

    pre._stop = ModeTransitions()
    _set_mode(pre.state_dir, "gaming")
    pre._fs_watcher_loop()

    assert observer.starts == 1
    assert len(observer.scheduled) == 2
    assert len(observer.unscheduled) == 2
    assert observer.stops == observer.joins == 1
    assert pre._dirty_paths == {}

class _Noop:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class _Rag:
    index_reset = False

    @staticmethod
    def workspace_id(_root):
        return "workspace"


class _StopOnWait:
    def __init__(self, stop_event):
        self.stop_event = stop_event
        self.timeouts = []

    def wait(self, timeout=None):
        self.timeouts.append(timeout)
        self.stop_event.set()
        return True

    def clear(self):
        pass

    def set(self):
        self.stop_event.set()


def _config(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    state_dir = tmp_path / "state"
    config_path.write_text(
        f'[server]\nstate_dir="{state_dir.as_posix()}"\n'
        '[hardware]\nprofile="cpu"\n'
        '[preprocessing]\nenabled=false\nfs_watcher_enabled=false\n',
        encoding="utf-8",
    )
    from local_ai_hub.config import load_config

    return load_config(str(config_path)), state_dir


def test_mode_pause_blocks_next_preprocessing_step(tmp_path, monkeypatch):
    config, state_dir = _config(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    tools = RepositoryTools(config)
    pre = ProjectPreprocessor(
        config, _Noop(), _Rag(), _Noop(), _Noop(), tools, code_index=CodeIndex(config, tools)
    )
    called = []
    monkeypatch.setattr(pre, "_step", lambda row: called.append(row) or True)
    try:
        set_operational_mode(state_dir, "gaming")
        result = pre._run_project_step({"root": str(repo.resolve())})
        assert result is None
        assert called == []
        assert pre.status()["paused"] is True
    finally:
        pre.close()


@pytest.mark.parametrize("mode", ["gaming", "maintenance"])
@pytest.mark.parametrize("worker", ["_cpu_loop", "_gpu_loop"])
def test_restricted_mode_pauses_background_worker_with_bounded_recheck(tmp_path, monkeypatch, mode, worker):
    config, state_dir = _config(tmp_path)
    config["preprocessing"]["poll_seconds"] = 30
    repo = tmp_path / "repo"
    repo.mkdir()
    tools = RepositoryTools(config)
    pre = ProjectPreprocessor(
        config, _Noop(), _Rag(), _Noop(), _Noop(), tools, code_index=CodeIndex(config, tools)
    )
    calls = []
    monkeypatch.setattr(pre, "_next_cpu_project", lambda: calls.append("cpu") or None)
    pre._cpu_wakeup = _StopOnWait(pre._stop)
    pre._gpu_wakeup = _StopOnWait(pre._stop)
    monkeypatch.setattr(preprocess_module, "set_current_thread_priority", lambda *_args: None)
    try:
        set_operational_mode(state_dir, mode)

        getattr(pre, worker)()

        wakeup = pre._cpu_wakeup if worker == "_cpu_loop" else pre._gpu_wakeup
        assert wakeup.timeouts == [pytest.approx(0.1)]
        assert calls == []
    finally:
        pre.close()


@pytest.mark.parametrize("mode", ["gaming", "maintenance"])
def test_cooperative_preprocess_yields_observe_restricted_mode(tmp_path, monkeypatch, mode):
    config, state_dir = _config(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    tools = RepositoryTools(config)
    pre = ProjectPreprocessor(
        config, _Noop(), _Rag(), _Noop(), _Noop(), tools, code_index=CodeIndex(config, tools)
    )
    pre.cpu_runs_during_foreground = True
    try:
        set_operational_mode(state_dir, mode)

        assert pre._yield() is True
        assert pre._gpu_yield() is True
    finally:
        pre.close()

