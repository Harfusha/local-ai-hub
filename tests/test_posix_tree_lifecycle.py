from types import SimpleNamespace
from threading import Lock

import pytest

from local_ai_hub import process_utils
from local_ai_hub import commands


@pytest.mark.parametrize("exited", [False, True])
def test_wait_observation_preserves_unreaped_leader(monkeypatch, exited):
    class Handle:
        pid = 4242
        returncode = None
        _waitpid_lock = Lock()

        def poll(self):
            raise AssertionError("poll would reap the leader")

    handle = Handle()

    def waitid(*_args):
        assert handle._waitpid_lock.locked()
        return SimpleNamespace(si_pid=handle.pid) if exited else None

    monkeypatch.setattr(commands, "os", SimpleNamespace(name="posix", waitid=waitid,
        P_PID=1, WEXITED=2, WNOHANG=4, WNOWAIT=8))
    assert commands._process_exited_without_reaping(handle) is exited


@pytest.mark.parametrize("descendants, expected", [(False, True), (True, False)])
def test_reaped_leader_only_confirms_cleanup_when_group_is_empty(monkeypatch, descendants, expected):
    pid = 4242
    identity = {"pid": pid, "creation_identity": "owned"}
    state = {"reaped": False, "signals": [], "clock": 0.0}

    def getpgid(_pid):
        if state["reaped"]:
            raise ProcessLookupError()
        return pid

    def killpg(_group, sig):
        state["signals"].append(sig)
        if sig == 0 and state["reaped"] and not descendants:
            raise ProcessLookupError()

    def monotonic():
        state["clock"] += 1.0
        return state["clock"]

    def waitpid(_pid, _flags):
        state["wait_lock_held"] = handle._waitpid_lock.locked()
        state["reaped"] = True
        return pid, 15

    class Handle:
        pid = 4242
        returncode = None
        _waitpid_lock = Lock()

        def _handle_exitstatus(self, _status):
            self.returncode = -15

    handle = Handle()
    monkeypatch.setattr(process_utils, "os", SimpleNamespace(name="posix", getpgid=getpgid, killpg=killpg, waitpid=waitpid, WNOHANG=1))
    monkeypatch.setattr(process_utils, "time", SimpleNamespace(monotonic=monotonic, sleep=lambda _: None))
    monkeypatch.setattr(process_utils, "signal", SimpleNamespace(SIGTERM=15, SIGKILL=9))
    monkeypatch.setattr(process_utils, "process_identity", lambda _pid: None if state["reaped"] else identity)

    result = process_utils.terminate_tree(
        pid, process_group=pid, expected_identity=identity, process_handle=handle, grace_seconds=0.5,
    )

    assert result is expected
    assert state["reaped"]
    assert state["wait_lock_held"]
    assert handle.returncode == -15
    assert state["signals"] == [15, 0, 9, 0]


@pytest.mark.parametrize("observed_start, owned", [("123", True), ("different", False)])
def test_linux_zombie_leader_keeps_owned_identity_until_reaped(monkeypatch, observed_start, owned):
    pid = 4242
    identity = {"pid": pid, "creation_identity": "123", "creation_identity_type": "linux_proc_starttime_ticks"}
    state = {"zombie": False, "reaped": False, "clock": 0.0}

    class Handle:
        returncode = None
        _waitpid_lock = Lock()

        def _handle_exitstatus(self, _status):
            self.returncode = -15

    handle = Handle()
    handle.pid = pid

    def killpg(_group, sig):
        if sig == 15:
            state["zombie"] = True
        elif sig == 0 and state["reaped"]:
            raise ProcessLookupError()

    def waitpid(_pid, _flags):
        assert handle._waitpid_lock.locked()
        state["reaped"] = True
        return pid, 15

    def monotonic():
        state["clock"] += 1
        return state["clock"]

    fake_os = SimpleNamespace(name="posix", getpgid=lambda _pid: pid, killpg=killpg,
        waitpid=waitpid, WNOHANG=1, waitid=lambda *_args: SimpleNamespace(si_pid=pid),
        P_PID=1, WEXITED=2, WNOWAIT=4)
    monkeypatch.setattr(process_utils, "os", fake_os)
    monkeypatch.setattr(process_utils, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(process_utils, "time", SimpleNamespace(monotonic=monotonic, sleep=lambda _: None))
    monkeypatch.setattr(process_utils, "signal", SimpleNamespace(SIGTERM=15, SIGKILL=9))
    monkeypatch.setattr(process_utils, "process_identity", lambda _pid: None if state["zombie"] else identity)
    monkeypatch.setattr(process_utils, "_linux_process_starttime", lambda _pid: observed_start)

    assert process_utils.terminate_tree(pid, process_group=pid, expected_identity=identity,
                                        process_handle=handle, grace_seconds=0.5) is owned
    assert state["reaped"] is owned
    assert handle.returncode == (-15 if owned else None)
