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

    def install(failure=None, output="HOST\\owner\n"):
        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            if failure is not None and argv[0] == failure[0]:
                raise failure[1]
            return subprocess.CompletedProcess(argv, 0, output if argv[0] == "whoami" else "", "")

        # Old implementation and hidden helper share the mocked OS boundary.
        monkeypatch.setattr(agent_events.subprocess, "run", run)
        monkeypatch.setattr(process_utils, "run_hidden", run)

    return install, descriptors, closed, calls, replacement


@pytest.mark.parametrize("command", ["whoami", "icacls"])
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
    assert calls


@pytest.mark.parametrize("output", ["", " \n", "unknown", "HOST\\owner\nOTHER\\user"])
def test_windows_unknown_account_is_closed(tmp_path, windows_reservation, output):
    install, descriptors, closed, calls, _ = windows_reservation
    install(output=output)
    path = tmp_path / "backup.sqlite3"
    with pytest.raises(PermissionError):
        AgentStateStore._reserve_backup_destination(path)
    assert not path.exists()
    assert closed == descriptors
    assert [call[0][0] for call in calls] == ["whoami"]


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
    assert [call[0][0] for call in calls] == ["whoami", "icacls"]
    assert calls[1][0][-1] == "HOST\\owner:(F)"
    for _, kwargs in calls:
        assert 0 < kwargs["timeout"] <= 1.0
        assert kwargs["check"] is True
        assert not kwargs.get("shell", False)


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
