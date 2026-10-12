from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


MANAGED_NAME = "acceptance"
OLLAMA_PID = 48123
JOB_NAME = "Local\\LocalAIHubManaged-" + "a" * 32


def _runtime(tmp_path: Path, *, managed_name: str = MANAGED_NAME):
    from local_ai_hub.ollama import OllamaRuntime

    return OllamaRuntime(
        {
            "server": {
                "state_dir": str(tmp_path),
                "ollama_url": "http://127.0.0.1:11434",
                "request_timeout_seconds": 0.1,
            },
            "headless": {"autostart_ollama": True, "manage_ollama": True},
            "llama_cpp": {"fallback_to_ollama": True},
            "ollama": {"enabled": True, "startup_timeout_seconds": 0.1},
        },
        managed_name=managed_name,
    )


def _owner(state_dir: Path, *, pid: int = OLLAMA_PID, role: str = MANAGED_NAME) -> dict:
    return {
        "pid": pid,
        "executable": r"C:\Ollama\ollama.exe",
        "creation_identity": "created-at-48123",
        "creation_identity_type": "windows_creation_time_100ns",
        "state_dir": str(state_dir.resolve()),
        "role": role,
        "windows_job_name": JOB_NAME,
    }


def _write_records(runtime, owner: dict | None, *, pid: int = OLLAMA_PID) -> Path:
    runtime.managed_pid_path.write_text(str(pid), encoding="utf-8")
    owner_path = runtime.state_dir / f"{runtime.managed_name}.owner.json"
    if owner is not None:
        owner_path.write_text(json.dumps(owner), encoding="utf-8")
    return owner_path


def _forbid_pid_signal(monkeypatch, module) -> None:
    monkeypatch.setattr(
        module,
        "terminate_tree",
        lambda *_args, **_kwargs: pytest.fail("managed stop must use the validated named job, not a PID"),
        raising=False,
    )


@pytest.mark.skipif(os.name != "nt", reason="cross-process named Job Object contract is Windows-specific")
def test_cross_process_stop_validates_owner_and_terminates_named_job(tmp_path: Path, monkeypatch):
    import local_ai_hub.ollama as module

    runtime = _runtime(tmp_path)
    owner = _owner(tmp_path)
    owner_path = _write_records(runtime, owner)
    runtime._managed_process = None
    calls = []
    handle = object()

    def owner_state(record, state_dir, role):
        calls.append(("owner_state", record, Path(state_dir), role))
        assert record == owner
        assert Path(state_dir) == tmp_path
        assert role == MANAGED_NAME
        return "owned"

    monkeypatch.setattr(module, "process_owner_state", owner_state, raising=False)
    monkeypatch.setattr(module, "open_named_job_object",
                        lambda name: calls.append(("open", name)) or handle, raising=False)
    monkeypatch.setattr(
        module, "windows_job_contains_process",
        lambda job, pid, record: calls.append(("contains", job, pid, record)) or True,
        raising=False,
    )
    monkeypatch.setattr(
        module, "terminate_job_object",
        lambda job: calls.append(("terminate", job)) or True,
        raising=False,
    )
    monkeypatch.setattr(
        module, "wait_job_object_empty",
        lambda job, *args, **kwargs: calls.append(("wait_empty", job, args, kwargs)) or True,
        raising=False,
    )
    monkeypatch.setattr(
        module, "close_job_object",
        lambda job: calls.append(("close", job)) or True,
        raising=False,
    )
    monkeypatch.setattr(module, "pid_alive", lambda _pid: True)
    _forbid_pid_signal(monkeypatch, module)

    assert runtime.stop_managed_server() is True
    assert calls[0] == ("owner_state", owner, tmp_path, MANAGED_NAME)
    assert ("open", JOB_NAME) in calls
    assert ("contains", handle, OLLAMA_PID, owner) in calls
    assert ("terminate", handle) in calls
    assert any(call[0] == "wait_empty" and call[1] is handle for call in calls)
    assert ("close", handle) in calls
    assert not runtime.managed_pid_path.exists()
    assert not owner_path.exists()


@pytest.mark.skipif(os.name != "nt", reason="named jobs are Windows-specific")
def test_stale_owner_without_named_job_cleans_only_private_markers(tmp_path: Path, monkeypatch):
    import local_ai_hub.ollama as module

    runtime = _runtime(tmp_path)
    owner = _owner(tmp_path)
    owner_path = _write_records(runtime, owner)
    opened = []
    monkeypatch.setattr(module, "process_owner_state", lambda *_args: "stale", raising=False)
    monkeypatch.setattr(
        module, "open_named_job_object", lambda name: opened.append(name) or None, raising=False,
    )
    monkeypatch.setattr(module, "pid_alive", lambda _pid: False)
    _forbid_pid_signal(monkeypatch, module)

    assert runtime.stop_managed_server() is True
    assert opened == [JOB_NAME]
    assert not runtime.managed_pid_path.exists()
    assert not owner_path.exists()


@pytest.mark.skipif(os.name != "nt", reason="named Job Object membership is Windows-specific")
def test_stale_owner_with_nonempty_named_job_fails_closed(tmp_path: Path, monkeypatch):
    import local_ai_hub.ollama as module

    runtime = _runtime(tmp_path)
    owner = _owner(tmp_path)
    owner_path = _write_records(runtime, owner)
    handle = object()
    calls = []
    closed = []
    monkeypatch.setattr(module, "process_owner_state", lambda *_args: "stale", raising=False)
    monkeypatch.setattr(module, "open_named_job_object", lambda _name: handle, raising=False)
    monkeypatch.setattr(
        module, "windows_job_contains_process",
        lambda job, pid, record: calls.append((job, pid, record)) or True,
        raising=False,
    )
    monkeypatch.setattr(
        module, "terminate_job_object",
        lambda *_args: pytest.fail("stale sidecar cannot authorize a nonempty job termination"),
        raising=False,
    )
    monkeypatch.setattr(
        module, "close_job_object", lambda job: closed.append(job) or True, raising=False,
    )
    monkeypatch.setattr(module, "wait_job_object_empty", lambda *_a: False)
    _forbid_pid_signal(monkeypatch, module)

    assert runtime.stop_managed_server() is False
    assert calls == []
    assert closed == [handle]
    assert runtime.managed_pid_path.exists()
    assert owner_path.exists()


@pytest.mark.skipif(os.name != "nt", reason="named Job Object membership is Windows-specific")
def test_owned_sidecar_without_matching_job_membership_fails_closed(tmp_path: Path, monkeypatch):
    import local_ai_hub.ollama as module

    runtime = _runtime(tmp_path)
    owner = _owner(tmp_path)
    owner_path = _write_records(runtime, owner)
    handle = object()
    calls = []
    monkeypatch.setattr(module, "process_owner_state", lambda *_args: "owned", raising=False)
    monkeypatch.setattr(module, "open_named_job_object", lambda _name: handle, raising=False)
    monkeypatch.setattr(
        module, "windows_job_contains_process",
        lambda job, pid, record: calls.append((job, pid, record)) or False,
        raising=False,
    )
    monkeypatch.setattr(
        module, "terminate_job_object",
        lambda *_args: pytest.fail("job membership failure must prevent termination"),
        raising=False,
    )
    monkeypatch.setattr(
        module, "close_job_object",
        lambda job: calls.append(("close", job)) or True,
        raising=False,
    )
    _forbid_pid_signal(monkeypatch, module)

    assert runtime.stop_managed_server() is False
    assert calls[0] == (handle, OLLAMA_PID, owner)
    assert ("close", handle) in calls
    assert runtime.managed_pid_path.exists()
    assert owner_path.exists()


@pytest.mark.parametrize("case", ["unknown", "wrong-scope", "malformed", "pid-only-live"])
def test_invalid_or_unscoped_owner_never_authorizes_stop(tmp_path: Path, monkeypatch, case: str):
    import local_ai_hub.ollama as module

    runtime = _runtime(tmp_path)
    owner = _owner(tmp_path)
    owner_path = _write_records(runtime, owner)
    open_calls = []
    state_calls = []

    if case == "malformed":
        owner_path.write_text("{not-json", encoding="utf-8")
    elif case == "pid-only-live":
        owner_path.unlink()
        monkeypatch.setattr(module, "pid_alive", lambda _pid: True)
    else:
        status = "unknown"

        def owner_state(record, state_dir, role):
            state_calls.append((record, Path(state_dir), role))
            if case == "wrong-scope":
                assert Path(state_dir) == tmp_path
                assert role == MANAGED_NAME
                assert record["state_dir"] != str(Path(state_dir).resolve()) or record["role"] != role
            return status

        if case == "wrong-scope":
            owner["state_dir"] = str((tmp_path / "other").resolve())
            owner_path.write_text(json.dumps(owner), encoding="utf-8")
        monkeypatch.setattr(module, "process_owner_state", owner_state, raising=False)
        monkeypatch.setattr(module, "pid_alive", lambda _pid: True)

    monkeypatch.setattr(
        module, "open_named_job_object", lambda name: open_calls.append(name) or object(), raising=False,
    )
    monkeypatch.setattr(
        module, "windows_job_contains_process",
        lambda *_args: pytest.fail("invalid owner must be rejected before job membership"),
        raising=False,
    )
    monkeypatch.setattr(
        module, "terminate_job_object",
        lambda *_args: pytest.fail("invalid owner cannot authorize job termination"),
        raising=False,
    )
    _forbid_pid_signal(monkeypatch, module)

    assert runtime.stop_managed_server() is False
    assert open_calls == []
    assert runtime.managed_pid_path.exists()
    if case != "malformed":
        assert state_calls or case == "pid-only-live"


@pytest.mark.parametrize("manage", [True, False])
def test_online_external_server_is_borrowed_without_owner_or_pid_mutation(
    tmp_path: Path, monkeypatch, manage: bool,
):
    import local_ai_hub.ollama as module

    runtime = _runtime(tmp_path)
    runtime.config["headless"]["manage_ollama"] = manage
    monkeypatch.setattr(runtime, "is_online", lambda: True)
    monkeypatch.setattr(module, "find_listening_pid", lambda _port: 90123, raising=False)
    monkeypatch.setattr(
        module, "process_executable", lambda _pid: r"C:\Ollama\ollama.exe", raising=False,
    )
    monkeypatch.setattr(module, "pid_alive", lambda _pid: True)
    monkeypatch.setattr(
        module, "popen_managed",
        lambda *_args, **_kwargs: pytest.fail("online external server must be borrowed, not spawned"),
        raising=False,
    )
    _forbid_pid_signal(monkeypatch, module)

    assert runtime.ensure_running() is True
    assert runtime.stop_managed_server() is True
    assert not runtime.managed_pid_path.exists()
    assert not (tmp_path / f"{MANAGED_NAME}.owner.json").exists()


@pytest.mark.parametrize(("owner_state", "expected"), [("owned", True), ("stale", False), ("unknown", False)])
def test_managed_profile_verifiable_requires_canonical_owned_identity(
    tmp_path: Path, monkeypatch, owner_state: str, expected: bool,
):
    import local_ai_hub.ollama as module
    import local_ai_hub.process_utils as process_utils

    runtime = _runtime(tmp_path)
    owner = _owner(tmp_path)
    owner["profile"] = runtime._expected_managed_profile()
    owner_path = _write_records(runtime, owner)
    current = {
        key: owner[key] for key in ("pid", "executable", "creation_identity", "creation_identity_type")
    }
    if owner_state == "stale":
        current["creation_identity"] = "a-different-creation"
    elif owner_state == "unknown":
        current["executable"] = r"C:\Other\ollama.exe"
    monkeypatch.setattr(process_utils, "process_identity", lambda _pid: current)
    monkeypatch.setattr(module, "process_identity", lambda _pid: current, raising=False)
    monkeypatch.setattr(module, "pid_alive", lambda _pid: True)
    monkeypatch.setattr(runtime.llama_cpp, "available_models", lambda: [])
    monkeypatch.setattr(runtime.llama_cpp_managed, "status", lambda: {})

    status = runtime.managed_profile_status()
    assert status["managed"] is expected
    assert status["profile_verifiable"] is expected
    assert status["pid"] == (OLLAMA_PID if expected else None)
    assert owner_path.exists()


@pytest.mark.skipif(os.name != "nt", reason="named jobs are Windows-specific")
@pytest.mark.parametrize("failure", ["terminate", "wait", "open"])
def test_uncertain_job_cleanup_preserves_owner_records(tmp_path, monkeypatch, failure):
    import local_ai_hub.ollama as module

    runtime = _runtime(tmp_path)
    owner = _owner(tmp_path)
    path = _write_records(runtime, owner)
    monkeypatch.setattr(module, "process_owner_state", lambda *_a: "owned")
    def open_job(_name):
        if failure == "open":
            raise OSError("access denied")
        return 123
    monkeypatch.setattr(module, "open_named_job_object", open_job)
    monkeypatch.setattr(module, "windows_job_contains_process", lambda *_a: True)
    monkeypatch.setattr(module, "terminate_job_object", lambda *_a: failure != "terminate")
    monkeypatch.setattr(module, "wait_job_object_empty", lambda *_a: failure != "wait")
    monkeypatch.setattr(module, "close_job_object", lambda *_a: True)
    assert runtime.stop_managed_server() is False
    assert json.loads(path.read_text()) == owner
    assert runtime.managed_pid_path.read_text() == str(OLLAMA_PID)


def test_kernel_lock_contention_never_spawns_or_stops(tmp_path, monkeypatch):
    import local_ai_hub.ollama as module
    from local_ai_hub.process_utils import managed_process_lock

    runtime = _runtime(tmp_path)
    monkeypatch.setattr(runtime, "is_online", lambda: False)
    monkeypatch.setattr(module, "popen_managed", lambda *_a, **_k: pytest.fail("lock held by another owner"))
    monkeypatch.setattr(module, "terminate_tree", lambda *_a, **_k: pytest.fail("lock held by another owner"))
    with managed_process_lock(runtime.managed_lock_path) as acquired:
        assert acquired
        assert runtime.ensure_running() is False
        assert runtime.stop_managed_server() is False
    assert not runtime.managed_owner_path.exists()


def test_owned_profile_becomes_unverified_after_config_change(tmp_path, monkeypatch):
    import local_ai_hub.ollama as module

    runtime = _runtime(tmp_path)
    owner = _owner(tmp_path)
    owner["profile"] = runtime._expected_managed_profile()
    _write_records(runtime, owner)
    monkeypatch.setattr(module, "process_owner_state", lambda *_a: "owned")
    monkeypatch.setattr(runtime.llama_cpp, "available_models", lambda: [])
    monkeypatch.setattr(runtime.llama_cpp_managed, "status", lambda: {})
    runtime.config["ollama"]["num_parallel"] = 5
    status = runtime.managed_profile_status()
    assert status["managed"] is True
    assert status["profile_verifiable"] is False


def test_disabled_profile_flags_do_not_inherit_parent_enablement(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    for setting, variable in (("flash_attention", "OLLAMA_FLASH_ATTENTION"),
                              ("enable_vulkan", "OLLAMA_VULKAN"),
                              ("allow_integrated_gpu", "OLLAMA_IGPU_ENABLE")):
        runtime.config["ollama"][setting] = False
        monkeypatch.setenv(variable, "1")
    environment = runtime._configured_environment()
    assert "OLLAMA_FLASH_ATTENTION" not in environment
    assert "OLLAMA_VULKAN" not in environment
    assert "OLLAMA_IGPU_ENABLE" not in environment
