from __future__ import annotations

import ctypes
import os
import sys

import pytest

from local_ai_hub.opencode_appcontainer import (
    AppContainerCleanupError,
    ManagedAppContainerProcessSession,
    build_environment_block,
    file_info_identity,
)


def test_explicit_environment_block_is_sorted_and_double_terminated():
    buffer, pointer = build_environment_block({"PATH": "C:\\Windows", "TEMP": "C:\\Temp"})
    assert "".join(buffer[:len(buffer)]) == "PATH=C:\\Windows\0TEMP=C:\\Temp\0\0"
    assert len(buffer) > 1


@pytest.mark.parametrize("environment", [
    {"PATH": "ok", "AWS_SECRET_ACCESS_KEY": "secret"},
    {"PATH": "bad\0value"},
    {"=C:": "drive-current-directory"},
])
def test_environment_block_rejects_secrets_and_malformed_entries(environment):
    with pytest.raises(ValueError):
        build_environment_block(environment)


def test_bridge_environment_is_separate_and_requires_session_secret():
    pipe_name = r"\\.\pipe\lah-opencode-0123456789abcdef0123456789abcdef"
    secret = "ab" * 32
    with pytest.raises(ValueError, match="not allowed"):
        build_environment_block({"LOCAL_AI_PIPE_SECRET": secret})
    with pytest.raises(ValueError, match="256-bit secret"):
        build_environment_block({"LOCAL_AI_PIPE_NAME": pipe_name}, bridge_client=True)
    buffer, _ = build_environment_block({
        "LOCAL_AI_PIPE_NAME": pipe_name,
        "LOCAL_AI_PIPE_SECRET": secret,
        "LOCAL_AI_PIPE_PORT_FILE": r"C:\Users\test\bridge.port",
    }, bridge_client=True)
    assert "".join(buffer[:len(buffer)]).count("LOCAL_AI_PIPE_SECRET=") == 1


def test_appcontainer_primitives_fail_closed_off_windows():
    if os.name == "nt" and sys.platform.startswith("win"):
        pytest.skip("Windows-native behavior covered by the Windows integration test")
    from local_ai_hub.opencode_appcontainer import AppContainerProfile

    with pytest.raises(OSError, match="Windows-only"):
        AppContainerProfile.create()


def test_file_info_identity_uses_volume_and_file_index_fields():
    first = [0, None, None, None, 11, 0, 8, 2, 3, 4]
    replacement = [0, None, None, None, 11, 0, 8, 2, 3, 5]

    assert file_info_identity(first) == (11, 3, 4)
    assert file_info_identity(replacement) == (11, 3, 5)


def test_workspace_copyback_waits_for_all_successful_children_and_empty_job(monkeypatch):
    import local_ai_hub.opencode_appcontainer as appcontainer

    session = object.__new__(ManagedAppContainerProcessSession)
    session.workspace_snapshot = object()
    session.workspace_owner_pid = 11
    session.process_exit_codes = {11: 0}
    session.processes = [type("Child", (), {"pid": 22})()]
    session.job_handle = 99
    session.stage_handle = 77
    session.workspace_finalized = False
    session.state = "running"
    calls = []
    monkeypatch.setattr(appcontainer, "wait_job_object_empty", lambda *args, **kwargs: calls.append((args, kwargs)) or True)
    monkeypatch.setattr(appcontainer, "apply_workspace_changes", lambda *args, **kwargs: calls.append((args, kwargs)), raising=False)

    assert session._complete_workspace_if_ready() is None
    assert calls == []

    session.processes.clear()
    session.process_exit_codes[22] = 0
    session.state = "exited"
    result = session._complete_workspace_if_ready()
    repeated_result = session._complete_workspace_if_ready()

    assert result is None
    assert repeated_result is None
    assert len(calls) == 2
    assert calls[0][0] == (99,)
    assert calls[1][1] == {"staging_handle": 77}


def test_workspace_copyback_is_skipped_after_nonzero_child_exit(monkeypatch):
    import local_ai_hub.opencode_appcontainer as appcontainer

    session = object.__new__(ManagedAppContainerProcessSession)
    session.workspace_snapshot = object()
    session.workspace_owner_pid = 11
    session.process_exit_codes = {11: 1}
    session.processes = []
    session.job_handle = 99
    session.stage_handle = 77
    session.workspace_finalized = False
    session.state = "exited"
    calls = []
    monkeypatch.setattr(appcontainer, "wait_job_object_empty", lambda *args, **kwargs: calls.append("job") or True)
    monkeypatch.setattr(appcontainer, "apply_workspace_changes", lambda *args, **kwargs: calls.append("copy"), raising=False)

    assert session._complete_workspace_if_ready() is None
    assert calls == []


def test_successful_main_child_exit_triggers_workspace_copyback(monkeypatch):
    import local_ai_hub.opencode_appcontainer as appcontainer

    session = object.__new__(ManagedAppContainerProcessSession)
    session.workspace_snapshot = object()
    session.workspace_owner_pid = 11
    session.process_exit_codes = {}
    session.workspace_transfer_result = None
    session.workspace_finalized = False
    session.processes = []
    child = type("Child", (), {
        "pid": 11,
        "wait": lambda self, timeout_ms: 0,
        "close": lambda self: None,
    })()
    session.processes.append(child)
    session.process = child
    session.job_handle = 99
    session.stage_handle = 77
    session.state = "running"
    calls = []
    monkeypatch.setattr(appcontainer, "wait_job_object_empty", lambda *args, **kwargs: calls.append("job") or True)
    monkeypatch.setattr(appcontainer, "apply_workspace_changes", lambda *args, **kwargs: "applied", raising=False)

    assert session.wait_child(11) == 0

    assert session.workspace_transfer_result == "applied"
    assert session.state == "exited"
    assert calls == ["job"]


def test_workspace_copyback_fails_closed_when_job_empty_is_unknown(monkeypatch):
    import local_ai_hub.opencode_appcontainer as appcontainer

    session = object.__new__(ManagedAppContainerProcessSession)
    session.workspace_snapshot = object()
    session.workspace_owner_pid = 11
    session.process_exit_codes = {11: 0}
    session.processes = []
    session.job_handle = 99
    session.stage_handle = 77
    session.workspace_finalized = False
    session.state = "exited"
    calls = []
    monkeypatch.setattr(appcontainer, "wait_job_object_empty", lambda *args, **kwargs: calls.append("job") or False)
    monkeypatch.setattr(appcontainer, "apply_workspace_changes", lambda *args, **kwargs: calls.append("copy"), raising=False)

    with pytest.raises(AppContainerCleanupError, match="Job is not empty"):
        session._complete_workspace_if_ready()

    assert session.state == "cleanup_failed"
    assert calls == ["job"]
