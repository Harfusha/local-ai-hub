"""A numeric POSIX process group alone is not permission to signal it."""

from threading import Lock
from types import SimpleNamespace

from local_ai_hub import process_utils


def _posix(monkeypatch):
    calls = []
    def killpg(group, sig):
        calls.append(sig)
        if sig == 0:
            raise ProcessLookupError
    monkeypatch.setattr(process_utils.os, "name", "posix")
    monkeypatch.setattr(process_utils.os, "getpgid", lambda pid: 4321, raising=False)
    monkeypatch.setattr(process_utils.os, "killpg", killpg, raising=False)
    return calls


def _process_handle(pid=4321):
    return SimpleNamespace(pid=pid, returncode=None, _waitpid_lock=Lock())


def test_group_cleanup_without_captured_identity_never_signals(monkeypatch):
    calls = _posix(monkeypatch)
    ticks = iter([10.0, 11.0])
    monkeypatch.setattr(process_utils.time, "monotonic", lambda: next(ticks, 12.0))
    assert process_utils.terminate_tree(
        4321, process_group=4321, grace_seconds=0, process_handle=_process_handle(),
    ) is False
    assert calls == []


def test_group_cleanup_rejects_reused_leader_before_term(monkeypatch):
    calls = _posix(monkeypatch)
    expected = {"pid": 4321, "creation_identity": 1}
    monkeypatch.setattr(process_utils, "process_identity", lambda pid: {**expected, "creation_identity": 2})
    assert process_utils.terminate_tree(
        4321, process_group=4321, expected_identity=expected, grace_seconds=0,
        process_handle=_process_handle(),
    ) is False
    assert calls == []


def test_group_cleanup_revalidates_identity_before_escalation(monkeypatch):
    calls = _posix(monkeypatch)
    expected = {"pid": 4321, "creation_identity": 1}
    identities = iter([expected, {**expected, "creation_identity": 2}])
    process_handle = _process_handle()
    monkeypatch.setattr(process_utils, "process_identity", lambda pid: next(identities))
    ticks = iter([10.0, 11.0])
    monkeypatch.setattr(process_utils.time, "monotonic", lambda: next(ticks, 12.0))
    assert process_utils.terminate_tree(
        4321, process_group=4321, expected_identity=expected, grace_seconds=0,
        process_handle=process_handle,
    ) is False
    assert calls == [process_utils.signal.SIGTERM]


def test_group_signal_holds_popen_wait_lock(monkeypatch):
    calls = _posix(monkeypatch)
    expected = {"pid": 4321, "creation_identity": 1}
    process_handle = _process_handle()
    lock_states = []

    def killpg(group, sig):
        lock_states.append(process_handle._waitpid_lock.locked())
        calls.append(sig)
        if sig == 0:
            raise ProcessLookupError

    monkeypatch.setattr(process_utils.os, "killpg", killpg, raising=False)
    monkeypatch.setattr(process_utils, "process_identity", lambda pid: expected)
    ticks = iter([10.0, 11.0])
    monkeypatch.setattr(process_utils.time, "monotonic", lambda: next(ticks, 12.0))

    process_utils.terminate_tree(
        4321, process_group=4321, expected_identity=expected, grace_seconds=0,
        process_handle=process_handle,
    )

    assert calls
    assert all(lock_states)
    assert not process_handle._waitpid_lock.locked()
