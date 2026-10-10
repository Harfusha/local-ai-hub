from __future__ import annotations

import os

from local_ai_hub import client as client_module


def test_acquire_start_lock_recovers_stale_owner(tmp_path, monkeypatch) -> None:
    lock_path = tmp_path / "hub.start.lock"
    lock_path.write_text("123 1 nonce test_start_id 7", encoding="ascii")
    os.utime(lock_path, (0, 0))
    monkeypatch.setattr(client_module, "process_identity", lambda _pid: None)
    monkeypatch.setattr(client_module, "pid_alive", lambda _pid: False)

    owner_lock = client_module._acquire_start_lock(lock_path, stale_seconds=1)
    assert owner_lock is not None
    try:
        owner_lock.seek(0)
        assert int(owner_lock.read().split()[0]) == os.getpid()
    finally:
        owner_lock.close()


def test_acquire_start_lock_recovers_reused_pid(tmp_path, monkeypatch) -> None:
    lock_path = tmp_path / "hub.start.lock"
    lock_path.write_text("123 1 nonce test_start_id 7", encoding="ascii")
    os.utime(lock_path, (0, 0))
    monkeypatch.setattr(
        client_module,
        "process_identity",
        lambda _pid: {
            "creation_identity_type": "test_start_id",
            "creation_identity": 8,
        },
    )
    monkeypatch.setattr(client_module, "pid_alive", lambda _pid: True)

    owner_lock = client_module._acquire_start_lock(lock_path, stale_seconds=20)
    assert owner_lock is not None
    owner_lock.close()
