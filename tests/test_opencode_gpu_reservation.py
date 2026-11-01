from types import SimpleNamespace
import os
import subprocess
import sys
import threading
import time

import pytest

from local_ai_hub.scheduler import AffinityScheduler


def test_existing_scheduler_observes_external_reservation(tmp_path):
    config = {"server": {"state_dir": str(tmp_path)}}
    runtime = SimpleNamespace(loaded_models=lambda: [], loaded_model_details=lambda: [])
    owner = AffinityScheduler(runtime, config)
    other = AffinityScheduler(runtime, config)
    try:
        token = owner.reserve_external_gpu()
        assert token is not None
        assert not other.acquire_background_gpu(0)
        assert other.foreground_busy()
        assert not other.background_allowed()
        assert owner.release_external_gpu(token)
        assert other.acquire_background_gpu(0)
        other.release_background_gpu()
    finally:
        owner.close()
        other.close()


def test_existing_scheduler_does_not_dispatch_during_new_external_reservation(tmp_path):
    config = {"server": {"state_dir": str(tmp_path)}}
    preparations, calls = [], []
    runtime = SimpleNamespace(loaded_model_details=lambda: [],
                              prepare_model=lambda *a, **k: preparations.append(True))
    owner = AffinityScheduler(runtime, config)
    other = AffinityScheduler(runtime, config)
    try:
        token = owner.reserve_external_gpu()
        assert token
        with pytest.raises(TimeoutError):
            other.submit("model", source="test", execute=lambda: calls.append(True), wait_timeout=0.2)
        assert preparations == [] and calls == []
        assert owner.release_external_gpu(token)
    finally:
        owner.close()
        other.close()


def test_background_worker_never_terminates_an_unmanaged_listener(tmp_path, monkeypatch):
    from local_ai_hub import background_gpu

    attempts, releases, stopped = [], [], []
    scheduler = SimpleNamespace(acquire_background_gpu=lambda _: True, release_background_gpu=lambda: releases.append(True),
                                foreground_busy=lambda: False)
    config = {"server": {"state_dir": str(tmp_path)}, "models": {"background_code": "test-model"},
              "background_gpu": {"enabled": True, "idle_seconds": 0}}
    worker = background_gpu.IdleGPUWorker(config, scheduler)
    worker.runtime = SimpleNamespace(is_online=lambda: True, managed_profile_status=lambda: {"managed": False},
                                     stop_managed_server=lambda: stopped.append(True))
    monkeypatch.setattr(background_gpu, "find_listening_pid", lambda _port: 12345, raising=False)
    monkeypatch.setattr(background_gpu, "process_executable", lambda _pid: "ollama.exe", raising=False)
    def forbidden(pid, **_kwargs):
        attempts.append(pid)
        raise RuntimeError("unmanaged process must never be terminated")
    monkeypatch.setattr(background_gpu, "terminate_tree", forbidden, raising=False)
    try:
        assert worker._acquire_session() is False
        assert attempts == []
        assert releases == [True]
        assert stopped == []
        assert worker._stats["unmanaged_endpoint_rejections"] == 1
    finally:
        worker._executor.shutdown(wait=True, cancel_futures=True)


def test_background_worker_rejects_endpoint_borrowed_during_start(tmp_path):
    from local_ai_hub.background_gpu import IdleGPUWorker

    releases, prepared, stopped = [], [], []
    scheduler = SimpleNamespace(acquire_background_gpu=lambda _: True, release_background_gpu=lambda: releases.append(True),
                                foreground_busy=lambda: False)
    config = {"server": {"state_dir": str(tmp_path)}, "models": {"background_code": "test-model"},
              "background_gpu": {"enabled": True, "idle_seconds": 0}}
    worker = IdleGPUWorker(config, scheduler)
    worker.runtime = SimpleNamespace(is_online=lambda: False, ensure_running=lambda: True,
        managed_profile_status=lambda: {"managed": False}, prepare_model=lambda *a, **k: prepared.append(True),
        stop_managed_server=lambda: stopped.append(True))
    try:
        assert worker._acquire_session() is False
        assert prepared == [] and stopped == []
        assert releases == [True]
        assert worker._stats["unmanaged_endpoint_rejections"] == 1
    finally:
        worker._executor.shutdown(wait=True, cancel_futures=True)


def test_cpu_worker_rejects_endpoint_borrowed_during_start(tmp_path):
    from local_ai_hub.background_gpu import IdleGPUWorker

    prepared, stopped = [], []
    config = {"server": {"state_dir": str(tmp_path)}, "models": {"background_code": "test-model"},
              "background_gpu": {"enabled": True, "cpu_fallback_enabled": True}}
    worker = IdleGPUWorker(config, SimpleNamespace())
    worker.cpu_runtime = SimpleNamespace(is_online=lambda: False, ensure_running=lambda: True,
        managed_profile_status=lambda: {"managed": False}, prepare_model=lambda *a, **k: prepared.append(True),
        stop_managed_server=lambda: stopped.append(True))
    try:
        assert worker._acquire_cpu_session() is False
        assert prepared == [] and stopped == []
    finally:
        worker._executor.shutdown(wait=True, cancel_futures=True)


def test_background_worker_accepts_verified_managed_endpoint(tmp_path):
    from local_ai_hub.background_gpu import IdleGPUWorker

    prepared = []
    scheduler = SimpleNamespace(acquire_background_gpu=lambda _: True, release_background_gpu=lambda: None,
                                foreground_busy=lambda: False)
    config = {"server": {"state_dir": str(tmp_path)}, "models": {"background_code": "test-model"},
              "background_gpu": {"enabled": True, "idle_seconds": 0}}
    worker = IdleGPUWorker(config, scheduler)
    worker.runtime = SimpleNamespace(is_online=lambda: True, ensure_running=lambda: True,
        managed_profile_status=lambda: {"managed": True}, prepare_model=lambda *a, **k: prepared.append(True),
        loaded_model_details=lambda: [{"name": "test-model", "cpu_offload_fraction": 0}])
    try:
        assert worker._acquire_session() is True
        assert prepared == [True]
    finally:
        worker._executor.shutdown(wait=True, cancel_futures=True)


def test_external_reservation_fences_background_and_idle_unload(tmp_path):
    runtime = SimpleNamespace(loaded_model_details=lambda: [])
    scheduler = AffinityScheduler(runtime, {"server": {"state_dir": str(tmp_path)}, "scheduler": {"idle_timeout_seconds": 1}})
    try:
        token = scheduler.reserve_external_gpu()
        assert isinstance(token, str) and token
        assert scheduler.reserve_external_gpu() is None
        assert scheduler.foreground_busy()
        assert not scheduler.background_allowed()
        assert not scheduler.acquire_background_gpu(0)
        with scheduler._cond:
            scheduler._active_model = "model"
            scheduler._idle_owned_model = "model"
            scheduler._last_model_activity = time.monotonic() - 10
            assert scheduler._claim_idle_unload(time.monotonic()) is None
            scheduler._active_model = None
        assert not scheduler.release_external_gpu("not-the-token")
        assert not scheduler.release_external_gpu("ž")
        assert not scheduler.acquire_background_gpu(0)
        assert scheduler.release_external_gpu(token)
        assert not scheduler.release_external_gpu(token)
    finally:
        scheduler.close()


def test_scheduler_does_not_dispatch_internal_work_during_external_reservation(tmp_path):
    runtime = SimpleNamespace(loaded_model_details=lambda: [])
    scheduler = AffinityScheduler(runtime, {"server": {"state_dir": str(tmp_path)}})
    called = threading.Event()
    try:
        token = scheduler.reserve_external_gpu()
        assert token
        with pytest.raises(TimeoutError):
            scheduler.submit("model", source="test", execute=lambda: called.set() or {"success": True}, wait_timeout=0.15)
        assert not called.is_set()
        assert scheduler.release_external_gpu(token)
    finally:
        scheduler.close()


def test_external_reservation_is_atomic_between_competing_clients(tmp_path):
    scheduler = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), {"server": {"state_dir": str(tmp_path)}})
    barrier = threading.Barrier(3)
    results = []
    def reserve():
        barrier.wait(timeout=2)
        results.append(scheduler.reserve_external_gpu())
    threads = [threading.Thread(target=reserve) for _ in range(2)]
    try:
        for thread in threads:
            thread.start()
        barrier.wait(timeout=2)
        for thread in threads:
            thread.join(timeout=2)
            assert not thread.is_alive()
        assert sum(token is not None for token in results) == 1
        assert scheduler.release_external_gpu(next(token for token in results if token))
    finally:
        scheduler.close()


def test_external_reservation_survives_scheduler_restart(tmp_path):
    config = {"server": {"state_dir": str(tmp_path)}}
    runtime = SimpleNamespace(loaded_model_details=lambda: [])
    first = AffinityScheduler(runtime, config)
    token = first.reserve_external_gpu()
    assert token
    first.close()
    second = AffinityScheduler(runtime, config)
    try:
        assert second.foreground_busy()
        assert second.reserve_external_gpu() is None
        assert not second.acquire_background_gpu(0)
        assert not second.release_external_gpu("wrong-token")
        assert second.release_external_gpu(token)
    finally:
        second.close()


def test_corrupt_external_reservation_fails_closed(tmp_path):
    (tmp_path / "external-gpu-reservation").write_text("incomplete", encoding="ascii")
    scheduler = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), {"server": {"state_dir": str(tmp_path)}})
    try:
        assert scheduler.foreground_busy()
        assert scheduler.reserve_external_gpu() is None
        assert not scheduler.release_external_gpu("anything")
        assert not scheduler.acquire_background_gpu(0)
    finally:
        scheduler.close()


def test_reservation_sync_failure_keeps_fence_after_restart(tmp_path, monkeypatch):
    from local_ai_hub import scheduler as scheduler_module

    config = {"server": {"state_dir": str(tmp_path)}}
    runtime = SimpleNamespace(loaded_model_details=lambda: [])
    scheduler = AffinityScheduler(runtime, config)
    try:
        def fail_sync(_fd):
            raise OSError("sync failed")
        monkeypatch.setattr(scheduler_module.os, "fsync", fail_sync)
        assert scheduler.reserve_external_gpu() is None
        assert scheduler.foreground_busy()
    finally:
        scheduler.close()
    restarted = AffinityScheduler(runtime, config)
    try:
        assert restarted.foreground_busy()
        assert restarted.reserve_external_gpu() is None
    finally:
        restarted.close()


def test_external_reservation_requires_persistent_state_directory():
    scheduler = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), {})
    try:
        assert scheduler.reserve_external_gpu() is None
    finally:
        scheduler.close()


def test_reservation_survives_abrupt_process_exit(tmp_path):
    script = '''
import os, sys
from types import SimpleNamespace
from local_ai_hub.scheduler import AffinityScheduler
s=AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), {"server":{"state_dir":sys.argv[1]}})
if len(sys.argv)==2:
    print(s.reserve_external_gpu(), flush=True)
    os._exit(0)
assert s.foreground_busy() and s.reserve_external_gpu() is None
assert s.release_external_gpu(sys.argv[2])
s.close()
'''
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    first = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True, timeout=10, creationflags=flags, check=True)
    token = first.stdout.strip()
    assert token and token != "None"
    subprocess.run([sys.executable, "-c", script, str(tmp_path), token], capture_output=True, text=True, timeout=10, creationflags=flags, check=True)


@pytest.mark.parametrize("field,value", [("_inflight", 1), ("_switching", True), ("_background_gpu_lease", True)])
def test_external_reservation_rejects_existing_gpu_work(field, value, tmp_path):
    scheduler = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), {"server": {"state_dir": str(tmp_path)}})
    try:
        with scheduler._cond:
            original = getattr(scheduler, field)
            setattr(scheduler, field, value)
            assert scheduler.reserve_external_gpu() is None
            setattr(scheduler, field, original)
    finally:
        scheduler.close()
