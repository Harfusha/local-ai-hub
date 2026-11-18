from __future__ import annotations

import threading
from types import SimpleNamespace

import local_ai_hub.preprocess as preprocess_module
from local_ai_hub.preprocess import ProjectPreprocessor


def test_gpu_loop_survives_scheduler_selection_timeout() -> None:
    stop = threading.Event()

    class Wakeup:
        waits = 0

        def wait(self, timeout: float | None = None) -> bool:
            self.waits += 1
            if self.waits == 2:
                stop.set()
            return stop.is_set()

        def clear(self) -> None:
            pass

    preprocessor = object.__new__(ProjectPreprocessor)
    preprocessor.cfg = {"startup_delay_seconds": 0, "poll_seconds": 0.2}
    preprocessor._stop = stop
    preprocessor._paused = threading.Event()
    preprocessor._gpu_wakeup = Wakeup()
    preprocessor.background_gpu = SimpleNamespace(ready=lambda: True)
    preprocessor._background_work_allowed = lambda: True
    calls = 0

    def next_project(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("SQLite writer result timed out")
        return None

    preprocessor._next_gpu_project = next_project
    preprocessor._gpu_loop()

    assert calls == 2
    assert preprocessor._gpu_wakeup.waits == 2


def test_cpu_loop_survives_scheduler_selection_timeout(monkeypatch) -> None:
    stop = threading.Event()

    class Wakeup:
        waits = 0

        def wait(self, timeout: float | None = None) -> bool:
            self.waits += 1
            if self.waits == 2:
                stop.set()
            return stop.is_set()

        def clear(self) -> None:
            pass

    monkeypatch.setattr(preprocess_module, "set_current_thread_priority", lambda _priority: None)
    preprocessor = object.__new__(ProjectPreprocessor)
    preprocessor.cfg = {"startup_delay_seconds": 0, "poll_seconds": 0.2}
    preprocessor.cpu_priority = None
    preprocessor._stop = stop
    preprocessor._paused = threading.Event()
    preprocessor._cpu_wakeup = Wakeup()
    preprocessor._stats_lock = threading.Lock()
    preprocessor._stats = {"loops": 0, "errors": 0, "yields": 0}
    preprocessor.cpu_runs_during_foreground = True
    preprocessor._background_work_allowed = lambda: True
    preprocessor._run_idle_database_maintenance = lambda: None
    calls = 0

    def next_project(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("SQLite writer result timed out")
        return None

    preprocessor._next_cpu_project = next_project
    preprocessor._cpu_loop()

    assert calls == 2
    assert preprocessor._cpu_wakeup.waits == 2
