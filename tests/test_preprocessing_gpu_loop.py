from __future__ import annotations

import threading
from types import SimpleNamespace

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

    def next_project():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("SQLite writer result timed out")
        return None

    preprocessor._next_gpu_project = next_project
    preprocessor._gpu_loop()

    assert calls == 2
    assert preprocessor._gpu_wakeup.waits == 2
