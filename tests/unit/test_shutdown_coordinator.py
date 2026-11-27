from __future__ import annotations

import threading

import pytest

from local_ai_hub.shutdown import CloseCoordinator


def test_completed_cleanup_step_is_not_repeated_after_later_step_fails():
    completed_calls = []
    retry_calls = []

    def completed_step():
        completed_calls.append(True)

    def retry_step():
        retry_calls.append(True)
        if len(retry_calls) == 1:
            raise OSError("temporary cleanup failure")

    coordinator = CloseCoordinator([("completed", completed_step), ("retry", retry_step)])

    first = coordinator.close(timeout=1)
    second = coordinator.close(timeout=1)

    assert first["failed"] == ["retry"]
    assert second["success"] is True
    assert len(completed_calls) == 1
    assert len(retry_calls) == 2


@pytest.mark.parametrize("result", [{"success": False}, {"cleanup_unconfirmed": True}])
def test_unsuccessful_cleanup_result_is_reported_as_failed(result):
    coordinator = CloseCoordinator([("store", lambda: result)])

    report = coordinator.close(timeout=1)

    assert report["success"] is False
    assert report["failed"] == ["store"]
    assert report["components"]["store"]["error_type"] == "RuntimeError"


def test_concurrent_and_worker_initiated_close_never_waits_for_itself():
    started = threading.Event()
    release = threading.Event()
    reports = []
    coordinator = None

    def slow_cleanup():
        started.set()
        assert release.wait(2)
        reports.append(coordinator.close(timeout=0))

    coordinator = CloseCoordinator([("store", slow_cleanup)])

    initial = coordinator.close(timeout=0)
    assert started.wait(1)
    concurrent = coordinator.close(timeout=0)
    release.set()
    final = coordinator.close(timeout=1)
    assert coordinator._done.wait(1)
    completed = coordinator.close(timeout=0)

    assert initial["pending"] == ["store"]
    assert concurrent["pending"] == ["store"]
    assert reports[0]["pending"] == ["store"]
    assert final["success"] is True
    assert completed["success"] is True


@pytest.mark.parametrize("timeout", [True, -1, float("inf"), float("nan")])
def test_close_rejects_invalid_timeouts(timeout):
    coordinator = CloseCoordinator([])

    with pytest.raises(ValueError, match="finite and nonnegative"):
        coordinator.close(timeout=timeout)
