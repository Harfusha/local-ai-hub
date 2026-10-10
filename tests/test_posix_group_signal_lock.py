from __future__ import annotations

from types import SimpleNamespace

import local_ai_hub.process_utils as process_utils


def test_terminate_tree_holds_wait_lock_across_group_signals(monkeypatch) -> None:
    class TrackingLock:
        held = False

        def __enter__(self):
            assert not self.held
            self.held = True
            return self

        def __exit__(self, exc_type, exc, traceback):
            self.held = False

    wait_lock = TrackingLock()
    process = SimpleNamespace(pid=4321, returncode=None, _waitpid_lock=wait_lock)
    identity = {"pid": 4321, "creation_identity": "spawn-identity"}
    sigterm, sigkill = 15, 9
    signals: list[int] = []

    class PosixOS:
        name = "posix"

        @staticmethod
        def getpgid(pid: int) -> int:
            assert pid == process.pid
            assert wait_lock.held
            return 4321

        @staticmethod
        def killpg(group_id: int, sig: int) -> None:
            assert group_id == 4321
            assert wait_lock.held
            signals.append(sig)
            if sig == 0 and sigkill in signals:
                raise ProcessLookupError

    clock = iter((0.0, 1.0))
    monkeypatch.setattr(process_utils, "os", PosixOS())
    monkeypatch.setattr(process_utils, "signal", SimpleNamespace(SIGTERM=sigterm, SIGKILL=sigkill))
    monkeypatch.setattr(process_utils, "process_identity", lambda pid: identity)
    monkeypatch.setattr(
        process_utils,
        "time",
        SimpleNamespace(monotonic=lambda: next(clock, 1.0), sleep=lambda _: None),
    )

    result = process_utils.terminate_tree(
        process.pid,
        process_group=4321,
        expected_identity=identity,
        grace_seconds=0.5,
        process_handle=process,
    )

    assert result is True
    assert sigterm in signals
    assert sigkill in signals
    assert wait_lock.held is False
