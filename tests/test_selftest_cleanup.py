from __future__ import annotations

import shutil

from tools import selftest


def test_selftest_temp_cleanup_retries_windows_sharing_violation(tmp_path, monkeypatch):
    target = tmp_path / "selftest-state"
    target.mkdir()
    (target / "hub.log").write_text("finished", encoding="utf-8")
    real_rmtree = shutil.rmtree
    calls = []
    sleeps = []

    def flaky_rmtree(path, *args, **kwargs):
        calls.append(path)
        if len(calls) < 3:
            raise PermissionError("simulated Windows sharing violation")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(selftest.shutil, "rmtree", flaky_rmtree)
    monkeypatch.setattr(selftest.time, "sleep", sleeps.append)

    selftest._remove_tree_with_retry(target)

    assert len(calls) == 3
    assert sleeps == [0.1, 0.2]
    assert not target.exists()


def test_selftest_cleanup_passes_captured_identity_to_tree_terminator(monkeypatch):
    class Process:
        pid = 4321
        stdout = None
        stderr = None

        def communicate(self, timeout):
            return (b"", b"")

        def kill(self):
            raise AssertionError("live-process fallback should not run")

    process = Process()
    identity = {"pid": process.pid, "creation_identity": 987654321}
    calls = []

    def terminate(pid, **kwargs):
        calls.append((pid, kwargs))
        return True

    monkeypatch.setattr(selftest, "terminate_tree", terminate)

    selftest._terminate_selftest_process(process, identity)

    assert calls == [
        (
            process.pid,
            {
                "expected_identity": identity,
                "grace_seconds": 5.0,
                "process_handle": process,
            },
        )
    ]
