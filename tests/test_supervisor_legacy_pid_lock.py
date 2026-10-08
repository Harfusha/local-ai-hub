import json

from local_ai_hub import supervisor as supervisor_module


def test_supervisor_reclaims_stale_numeric_json_pid_lock(tmp_path, monkeypatch):
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
    supervisor.lock_path.write_text("21124", encoding="utf-8")

    assert supervisor.acquire() is True
    replacement = json.loads(supervisor.lock_path.read_text(encoding="utf-8"))
    assert replacement["pid"] == current_pid
    supervisor.release_lock()
