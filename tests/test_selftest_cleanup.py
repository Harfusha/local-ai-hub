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
