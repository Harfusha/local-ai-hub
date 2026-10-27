from types import SimpleNamespace
from threading import Lock

import pytest

from local_ai_hub import process_utils


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
    assert state["signals"] == [15, 0]
