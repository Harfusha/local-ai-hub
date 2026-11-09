import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from local_ai_hub.background_gpu import IdleGPUWorker
from local_ai_hub.scheduler import AffinityScheduler


class FakeTimer:
    instances = []

    def __init__(self, interval, callback):
        self.interval = interval
        self.callback = callback
        self.daemon = False
        self.cancelled = False
        self.instances.append(self)

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True


def make_worker(monkeypatch, stopped=True):
    monkeypatch.setattr(threading, "Timer", FakeTimer)
    FakeTimer.instances.clear()
    worker = IdleGPUWorker.__new__(IdleGPUWorker)
    worker._setup_lock = threading.RLock()
    worker._lock = threading.RLock()
    worker._closed = False
    worker._lease = True
    worker._active = 0
    worker._idle_release_timer = None
    worker._idle_release_seconds = 30
    worker._stop_unconfirmed = False
    worker._last_error = None
    worker._model_details = []
    released = []
    worker.scheduler = SimpleNamespace(release_background_gpu=lambda: released.append(True))
    worker.runtime = SimpleNamespace(stop_managed_server=lambda: stopped)
    return worker, released


def test_idle_lease_releases_after_confirmed_shutdown(monkeypatch):
    worker, released = make_worker(monkeypatch)
    worker._schedule_idle_release()
    FakeTimer.instances[-1].callback()
    assert released == [True]
    assert worker._lease is False


def test_stale_timer_cannot_stop_new_work(monkeypatch):
    worker, released = make_worker(monkeypatch)
    worker._schedule_idle_release()
    old = FakeTimer.instances[-1]
    with worker._setup_lock:
        worker._cancel_idle_release_locked()
        worker._active = 1
    old.callback()
    assert old.cancelled
    assert released == []
    assert worker._lease is True


def test_idle_stop_failure_retains_fence(monkeypatch):
    worker, released = make_worker(monkeypatch, stopped=False)
    worker._schedule_idle_release()
    FakeTimer.instances[-1].callback()
    assert released == []
    assert worker._lease is True
    assert worker._stop_unconfirmed is True


def test_idle_fence_release_failure_is_reported(monkeypatch):
    worker, _ = make_worker(monkeypatch)
    worker.scheduler.release_background_gpu = lambda: False
    worker._schedule_idle_release()
    FakeTimer.instances[-1].callback()
    assert "release" in worker._last_error


def test_completed_batch_arms_idle_release(monkeypatch):
    import local_ai_hub.operational_mode as mode
    import local_ai_hub.opencode_boundary as boundary

    worker, released = make_worker(monkeypatch)
    worker.config = {"server": {"state_dir": "unused"}}
    worker.parallel = 1
    worker.policy = object()
    worker._bg_config = {}
    worker.cpu_runtime = object()
    worker.cpu_policy = object()
    worker._cpu_config = {}
    worker._cpu_slot = threading.Lock()
    worker._configure_parallel_for_mode = lambda: True
    worker._acquire_session = lambda: True
    worker._foreground_requested = lambda: False
    worker._generate_one = lambda *args, **kwargs: {"success": True}
    worker._stats = {"batches": 0, "submitted": 0, "completed": 0, "failed": 0}
    monkeypatch.setattr(boundary, "generation_denial", lambda: None)
    monkeypatch.setattr(mode, "load_operational_mode", lambda _: SimpleNamespace(mode="active", degraded=False))
    with ThreadPoolExecutor(max_workers=1) as executor:
        worker._executor = executor
        assert worker.generate_many([{"prompt": "test"}]) == [{"success": True}]
    assert worker._active == 0
    assert FakeTimer.instances[-1].interval == 30
    FakeTimer.instances[-1].callback()
    assert released == [True]


def test_idle_release_clears_real_scheduler_fence(tmp_path, monkeypatch):
    worker, _ = make_worker(monkeypatch)
    scheduler = AffinityScheduler(
        SimpleNamespace(loaded_model_details=lambda: []),
        {"server": {"state_dir": str(tmp_path)}},
    )
    try:
        with scheduler._cond:
            assert scheduler._claim_internal_gpu()
            scheduler._background_gpu_lease = True
        worker.scheduler = scheduler
        worker._schedule_idle_release()
        FakeTimer.instances[-1].callback()
        status = scheduler.gpu_reservation_operation(action="status")
        assert status["state"] == "free"
        assert status["reservation_present"] is False
    finally:
        scheduler.close()


def test_real_idle_timer_releases_scheduler_fence(tmp_path, monkeypatch):
    real_timer = threading.Timer
    worker, _ = make_worker(monkeypatch)
    monkeypatch.setattr(threading, "Timer", real_timer)
    scheduler = AffinityScheduler(
        SimpleNamespace(loaded_model_details=lambda: []),
        {"server": {"state_dir": str(tmp_path)}},
    )
    released = threading.Event()
    try:
        with scheduler._cond:
            assert scheduler._claim_internal_gpu()
            scheduler._background_gpu_lease = True
        original_release = scheduler.release_background_gpu

        def signal_release():
            result = original_release()
            released.set()
            return result

        monkeypatch.setattr(scheduler, "release_background_gpu", signal_release)
        worker.scheduler = scheduler
        worker._idle_release_seconds = 0.02
        worker._schedule_idle_release()
        assert released.wait(2)
        assert scheduler.gpu_reservation_operation(action="status")["state"] == "free"
    finally:
        with worker._setup_lock:
            worker._cancel_idle_release_locked()
        scheduler.close()
