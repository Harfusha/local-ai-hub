from types import SimpleNamespace

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

    class Handle:
        pid = 4242

        def poll(self):
            state["reaped"] = True
            return -15

    monkeypatch.setattr(process_utils, "os", SimpleNamespace(name="posix", getpgid=getpgid, killpg=killpg))
    monkeypatch.setattr(process_utils, "time", SimpleNamespace(monotonic=monotonic, sleep=lambda _: None))
    monkeypatch.setattr(process_utils, "signal", SimpleNamespace(SIGTERM=15, SIGKILL=9))
    monkeypatch.setattr(process_utils, "process_identity", lambda _pid: None if state["reaped"] else identity)

    result = process_utils._terminate_tree_unlocked(
        pid, process_group=pid, expected_identity=identity, process_handle=Handle(), grace_seconds=0.5,
    )

    assert result is expected
    assert state["reaped"]
    assert state["signals"] == [15, 0]
