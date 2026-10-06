from __future__ import annotations

from local_ai_hub import client


def test_acquire_start_lock_records_process_creation_identity(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        client,
        "process_identity",
        lambda _pid: {"creation_identity_type": "start_ticks", "creation_identity": "12345"},
    )
    marker = tmp_path / "start.lock"
    handle = client._acquire_start_lock(marker)
    assert handle is not None
    try:
        handle.seek(0)
        fields = handle.read().decode("ascii").split()
        assert fields[0].isdigit()
        assert fields[2:] == ["start_ticks", "12345"]
    finally:
        handle.close()


def test_stale_start_lock_checks_process_creation_identity(tmp_path, monkeypatch) -> None:
    marker = tmp_path / "start.lock"
    marker.write_text(f"{client.os.getpid()} 0 old_identity old_value", encoding="ascii")
    monkeypatch.setattr(client, "pid_alive", lambda _pid: True)
    monkeypatch.setattr(
        client,
        "process_identity",
        lambda _pid: {"creation_identity_type": "start_ticks", "creation_identity": "current"},
    )

    handle = client._acquire_start_lock(marker, stale_seconds=60)
    assert handle is not None
    try:
        handle.seek(0)
        fields = handle.read().decode("ascii").split()
        assert fields[0] == str(client.os.getpid())
        assert fields[2:] == ["start_ticks", "current"]
    finally:
        handle.close()
