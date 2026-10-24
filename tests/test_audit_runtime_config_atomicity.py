from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
from pathlib import Path
import threading
import tomllib

import pytest

import local_ai_hub.config as config_module
import local_ai_hub.file_locks as file_locks


def test_runtime_reset_serializes_before_waiting_update(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "config.toml"
    primary_bytes = b"[server]\nport = 9000\n"
    config_path.write_bytes(primary_bytes)
    target = config_module.runtime_override_path(config_path)
    target.write_bytes(b"[legacy]\nvalue = 3\n")

    reset_inside_lock = threading.Event()
    release_reset = threading.Event()
    update_lock_attempt = threading.Event()
    update_probe_acquired = []
    writer_role = threading.local()
    real_exclusive_update = config_module.exclusive_file_update

    class ObservedRLock:
        def __init__(self, lock):
            self.lock = lock

        def acquire(self, *args, **kwargs):
            if getattr(writer_role, "value", None) == "update":
                probe_acquired = self.lock.acquire(blocking=False)
                update_probe_acquired.append(probe_acquired)
                if probe_acquired:
                    self.lock.release()
                update_lock_attempt.set()
            return self.lock.acquire(*args, **kwargs)

        def release(self):
            return self.lock.release()

    lock_index = hash(os.path.normcase(str(target.resolve()))) % len(file_locks._LOCKS)
    locks = list(file_locks._LOCKS)
    locks[lock_index] = ObservedRLock(locks[lock_index])
    monkeypatch.setattr(file_locks, "_LOCKS", tuple(locks))

    @contextmanager
    def hold_reset_lock(path, **kwargs):
        with real_exclusive_update(path, **kwargs):
            if getattr(writer_role, "value", None) == "reset":
                reset_inside_lock.set()
                if not release_reset.wait(timeout=4):
                    raise TimeoutError("test did not release reset writer")
            yield

    monkeypatch.setattr(config_module, "exclusive_file_update", hold_reset_lock)

    def reset():
        writer_role.value = "reset"
        return config_module.save_runtime_overrides(config_path, {}, reset=True)

    def update():
        writer_role.value = "update"
        return config_module.save_runtime_overrides(config_path, {"from_update": True})

    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="runtime-config")
    futures = []
    try:
        reset_future = executor.submit(reset)
        futures.append(reset_future)
        assert reset_inside_lock.wait(timeout=3), "reset did not enter the serialized update section"

        update_future = executor.submit(update)
        futures.append(update_future)
        assert update_lock_attempt.wait(timeout=3), "update did not attempt the same writer lock"
        assert update_probe_acquired == [False], "update unexpectedly acquired the lock while reset held it"

        release_reset.set()
        assert reset_future.result(timeout=5) == target
        assert update_future.result(timeout=5) == target
    finally:
        release_reset.set()
        executor.shutdown(wait=True, cancel_futures=True)

    assert target.read_bytes() == b"from_update = true" + os.linesep.encode('ascii')
    assert tomllib.loads(target.read_text(encoding='utf-8')) == {'from_update': True}
    assert config_path.read_bytes() == primary_bytes


def test_runtime_override_replace_failure_preserves_both_files_and_cleans_temp(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "config.toml"
    primary_bytes = b"[server]\nport = 9000\n"
    config_path.write_bytes(primary_bytes)
    target = config_module.runtime_override_path(config_path)
    original_override = b"[features]\ndashboard = true\n"
    target.write_bytes(original_override)
    real_replace = os.replace

    def fail_target_replace(source, destination):
        if Path(destination) == target:
            raise OSError("injected atomic publication failure")
        return real_replace(source, destination)

    monkeypatch.setattr(config_module.os, "replace", fail_target_replace)

    with pytest.raises(OSError, match="injected atomic publication failure"):
        config_module.save_runtime_overrides(config_path, {"features": {"dashboard": False}})

    assert config_path.read_bytes() == primary_bytes
    assert target.read_bytes() == original_override
    assert list(tmp_path.glob(target.name + ".*.tmp")) == []
