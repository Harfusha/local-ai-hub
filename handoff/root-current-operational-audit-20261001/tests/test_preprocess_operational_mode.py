import json
import sys
import threading
import types
from pathlib import Path
from types import SimpleNamespace

from local_ai_hub.preprocess import ProjectPreprocessor


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
