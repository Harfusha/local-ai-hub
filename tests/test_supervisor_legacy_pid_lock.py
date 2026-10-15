import json

import pytest

from local_ai_hub import supervisor as supervisor_module


@pytest.mark.parametrize("raw_lock", ["21124", "not-json"])
def test_supervisor_preserves_unstructured_lock_without_owner_proof(tmp_path, monkeypatch, raw_lock):
    state_dir = tmp_path / "state"
    config = tmp_path / "hub.toml"
    config.write_text(
        f'[server]\nstate_dir = "{state_dir.as_posix()}"\nport = 11435\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(supervisor_module, "OllamaRuntime", lambda _config: object())
    current_pid = supervisor_module.os.getpid()
    monkeypatch.setattr(
        supervisor_module,
        "process_owner_record",
        lambda pid, path, role: {
            "pid": pid,
            "executable": "python",
            "creation_identity": "current",
            "creation_identity_type": "test",
            "state_dir": str(state_dir.resolve()),
            "role": role,
        },
    )
    monkeypatch.setattr(supervisor_module, "pid_alive", lambda _pid: False)

    def owner_state(owner, _path, _role):
        if isinstance(owner, dict) and owner["pid"] == current_pid:
            return "owned"
        return "unknown"

    monkeypatch.setattr(
        supervisor_module,
        "process_owner_state",
        owner_state,
    )
    supervisor = supervisor_module.Supervisor(str(config))
    supervisor.lock_path.write_text(raw_lock, encoding="utf-8")

    assert supervisor.acquire() is False
    assert supervisor.lock_path.read_text(encoding="utf-8") == raw_lock


def test_supervisor_reclaims_structured_owner_proven_stale(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    config = tmp_path / "hub.toml"
    config.write_text(
        f'[server]\nstate_dir = "{state_dir.as_posix()}"\nport = 11435\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(supervisor_module, "OllamaRuntime", lambda _config: object())
    current_pid = supervisor_module.os.getpid()
    current_owner = {
        "pid": current_pid,
        "executable": "python",
        "creation_identity": "current",
        "creation_identity_type": "test",
        "state_dir": str(state_dir.resolve()),
        "role": "supervisor",
    }
    stale_owner = {**current_owner, "pid": 21124, "creation_identity": "stale"}
    monkeypatch.setattr(supervisor_module, "process_owner_record", lambda *_args: current_owner)
    monkeypatch.setattr(
        supervisor_module,
        "process_owner_state",
        lambda owner, *_args: "owned" if owner == current_owner else "stale",
    )
    supervisor = supervisor_module.Supervisor(str(config))
    supervisor.lock_path.write_text(json.dumps(stale_owner, separators=(",", ":")), encoding="utf-8")

    assert supervisor.acquire() is True
    assert json.loads(supervisor.lock_path.read_text(encoding="utf-8"))["pid"] == current_pid
    supervisor.release_lock()
