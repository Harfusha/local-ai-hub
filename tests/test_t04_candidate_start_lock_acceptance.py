from __future__ import annotations

import os

from local_ai_hub import client as client_module


def test_live_start_lock_recovers_stale_partial_sidecar(tmp_path, monkeypatch) -> None:
    lock_path = tmp_path / "hub.start.lock"
    lock_path.write_text("123 1 nonce test_start_id 7", encoding="ascii")
    lock_path.with_name(f"{lock_path.name}.nonce.pid").write_text("", encoding="ascii")
    os.utime(lock_path, (0, 0))
    monkeypatch.setattr(client_module, "process_identity", lambda _pid: None)
    monkeypatch.setattr(client_module, "pid_alive", lambda _pid: False)

    assert client_module._live_start_lock(lock_path, stale_seconds=1) is False


def test_live_start_lock_rejects_reused_pid(tmp_path, monkeypatch) -> None:
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

    assert client_module._live_start_lock(lock_path, stale_seconds=20) is False
