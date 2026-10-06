from __future__ import annotations

import time

from local_ai_hub import client as client_module


def test_start_lock_marker_records_creation_identity(monkeypatch, tmp_path) -> None:
    import io

    handle = io.BytesIO()
    monkeypatch.setattr(
        client_module,
        "process_identity",
        lambda _pid: {
            "creation_identity_type": "test_start_id",
            "creation_identity": 7,
        },
    )

    client_module._write_start_lock_owner(handle)

    fields = handle.getvalue().decode("ascii").split()
    assert len(fields) == 4
    assert fields[2:] == ["test_start_id", "7"]
    assert float(fields[1]) <= time.time()


def test_start_lock_rejects_reused_pid_with_different_creation_identity(tmp_path, monkeypatch) -> None:
    lock_path = tmp_path / "hub.start.lock"
    lock_path.write_text("123 1 test_start_id 7", encoding="ascii")
    monkeypatch.setattr(client_module, "pid_alive", lambda _pid: True)
    monkeypatch.setattr(
        client_module,
        "process_identity",
        lambda _pid: {
            "creation_identity_type": "test_start_id",
            "creation_identity": 8,
        },
    )

    handle = client_module._acquire_start_lock(lock_path, stale_seconds=60)
    assert handle is not None
    handle.close()


def test_start_lock_keeps_same_live_process_identity(tmp_path, monkeypatch) -> None:
    lock_path = tmp_path / "hub.start.lock"
    lock_path.write_text("123 1 test_start_id 7", encoding="ascii")
    monkeypatch.setattr(client_module, "pid_alive", lambda _pid: True)
    monkeypatch.setattr(
        client_module,
        "process_identity",
        lambda _pid: {
            "creation_identity_type": "test_start_id",
            "creation_identity": 7,
        },
    )

    handle = client_module._acquire_start_lock(lock_path, stale_seconds=60)
    assert handle is None
