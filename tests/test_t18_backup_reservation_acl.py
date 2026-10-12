import os
import subprocess

import pytest

from local_ai_hub import agent_events, process_utils
from local_ai_hub.agent_events import AgentStateStore


@pytest.fixture
def windows_reservation(monkeypatch):
    descriptors = []
    closed = []
    calls = []
    replacement = []

    class WindowsOS:
        name = "nt"
        environ = {"USERNAME": "untrusted-environment-user"}

        def __getattr__(self, name):
            return getattr(os, name)

        def open(self, *args):
            descriptor = os.open(*args)
            descriptors.append(descriptor)
            return descriptor

        def close(self, descriptor):
            os.close(descriptor)
            closed.append(descriptor)
            if replacement:
                path = replacement.pop()
                path.rename(path.with_suffix(".original"))
                path.write_bytes(b"foreign replacement")

    monkeypatch.setattr(agent_events, "os", WindowsOS())

    def install(failure=None, identity_error=None):
        def process_sid():
            if identity_error is not None:
                raise identity_error
            if failure is not None and failure[0] == "process_token":
                raise failure[1]
            return "S-1-5-21-100-200-300-1001"

        monkeypatch.setattr(agent_events, "_windows_process_user_sid", process_sid)

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            if failure is not None and argv[0] == failure[0]:
                raise failure[1]
            assert argv[0] == "icacls", "identity must not spawn a child"
            return subprocess.CompletedProcess(argv, 0, "", "")

        # Keep the same fail-closed boundary with native process-token identity.
        monkeypatch.setattr(agent_events.subprocess, "run", run)
        monkeypatch.setattr(process_utils, "run_hidden", run)

    return install, descriptors, closed, calls, replacement


@pytest.mark.parametrize("command", ["process_token", "icacls"])
@pytest.mark.parametrize("error", [
    subprocess.CalledProcessError(5, "mock"),
    subprocess.TimeoutExpired("mock", 1.0),
    FileNotFoundError("missing ACL utility"),
    PermissionError("denied ACL utility"),
])
def test_windows_acl_failure_is_closed(tmp_path, windows_reservation, command, error):
    install, descriptors, closed, calls, _ = windows_reservation
    install((command, error))
    path = tmp_path / "backup.sqlite3"
    with pytest.raises(PermissionError) as raised:
        AgentStateStore._reserve_backup_destination(path)
    assert raised.value.__cause__ is error
    assert not path.exists()
    assert closed == descriptors
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    assert bool(calls) == (command == "icacls")


@pytest.mark.parametrize("message", ["token unavailable", "token user unavailable", "SID conversion failed", "invalid process SID"])
def test_windows_unknown_process_identity_is_closed(tmp_path, windows_reservation, message):
    install, descriptors, closed, calls, _ = windows_reservation
    install(identity_error=OSError(message))
    path = tmp_path / "backup.sqlite3"
    with pytest.raises(PermissionError):
        AgentStateStore._reserve_backup_destination(path)
    assert not path.exists()
    assert closed == descriptors
    assert calls == []


def test_windows_acl_success_is_bounded_and_uses_current_account(tmp_path, monkeypatch, windows_reservation):
    install, descriptors, closed, calls, _ = windows_reservation
    install()
    def forbid_unhidden_process(*args, **kwargs):
        pytest.fail("reservation must use process_utils.run_hidden")

    monkeypatch.setattr(agent_events.subprocess, "run", forbid_unhidden_process)
    path = tmp_path / "backup.sqlite3"
    identity = AgentStateStore._reserve_backup_destination(path)
    assert identity == (path.stat().st_dev, path.stat().st_ino)
    assert closed == descriptors
    assert [call[0][0] for call in calls] == ["icacls"]
    assert calls[0][0][-1] == "*S-1-5-21-100-200-300-1001:(F)"
    for _, kwargs in calls:
        assert 0 < kwargs["timeout"] <= 1.0
        assert kwargs["check"] is True
        assert not kwargs.get("shell", False)


def test_windows_acl_retries_one_bounded_timeout(tmp_path, monkeypatch, windows_reservation):
    install, descriptors, closed, calls, _ = windows_reservation
    install()
    acl_attempts = 0

    def run(argv, **kwargs):
        nonlocal acl_attempts
        calls.append((argv, kwargs))
        assert argv[0] == "icacls"
        acl_attempts += 1
        if acl_attempts == 1:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(process_utils, "run_hidden", run)
    path = tmp_path / "backup.sqlite3"

    identity = AgentStateStore._reserve_backup_destination(path)

    assert identity == (path.stat().st_dev, path.stat().st_ino)
    assert acl_attempts == 2
    assert closed == descriptors
    assert all(0 < kwargs["timeout"] <= 1.0 for _, kwargs in calls)


def test_windows_unexpected_exception_is_not_swallowed(tmp_path, windows_reservation):
    install, descriptors, closed, _, _ = windows_reservation
    error = RuntimeError("unexpected helper defect")
    install(("icacls", error))
    path = tmp_path / "backup.sqlite3"
    with pytest.raises(RuntimeError, match="unexpected helper defect") as raised:
        AgentStateStore._reserve_backup_destination(path)
    assert raised.value is error
    assert not path.exists()
    assert closed == descriptors


def test_windows_acl_failure_preserves_replaced_inode(tmp_path, windows_reservation):
    install, descriptors, closed, _, replacement = windows_reservation
    install(("icacls", PermissionError("ACL denied")))
    path = tmp_path / "backup.sqlite3"
    replacement.append(path)
    with pytest.raises(PermissionError):
        AgentStateStore._reserve_backup_destination(path)
    assert closed == descriptors
    assert path.read_bytes() == b"foreign replacement"
    assert path.stat().st_ino != path.with_suffix(".original").stat().st_ino


def test_windows_identity_race_is_rejected(tmp_path, monkeypatch, windows_reservation):
    install, descriptors, closed, _, _ = windows_reservation
    install()
    monkeypatch.setattr(AgentStateStore, "_backup_path_matches", staticmethod(lambda *_: False))
    path = tmp_path / "backup.sqlite3"
    with pytest.raises(RuntimeError, match="destination changed"):
        AgentStateStore._reserve_backup_destination(path)
    assert path.exists()
    assert closed == descriptors


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_posix_reservation_is_private(tmp_path):
    path = tmp_path / "backup.sqlite3"
    AgentStateStore._reserve_backup_destination(path)
    assert path.stat().st_mode & 0o777 == 0o600
