from __future__ import annotations

import pytest
from local_ai_hub.status_executor import StatusDependencyExecutor


def test_status_executor_invalid_max_workers_rejected():
    with pytest.raises(ValueError, match="max_workers must be positive"):
        StatusDependencyExecutor(max_workers=0, capacity=1)

    with pytest.raises(ValueError, match="max_workers must be positive"):
        StatusDependencyExecutor(max_workers=-1, capacity=1)


def test_status_executor_submit_non_callable_rejected_immediately():
    executor = StatusDependencyExecutor(max_workers=1, capacity=1)
    try:
        with pytest.raises(TypeError, match="callable"):
            executor.submit("not_callable")  # type: ignore[arg-type]

        # Ensure slot was not leaked by invalid submission
        future = executor.submit(lambda: 42)
        assert future.result(timeout=1.0) == 42
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def test_status_executor_properties_and_idempotent_shutdown():
    executor = StatusDependencyExecutor(max_workers=2, capacity=3)
    try:
        assert executor.capacity == 3
        assert executor.max_workers == 2
        assert executor.is_shutdown is False
        assert executor.pending_count == 0

        fut = executor.submit(lambda: 100)
        assert fut.result(timeout=1.0) == 100
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

    assert executor.is_shutdown is True
    # Idempotent shutdown call should succeed without error
    executor.shutdown(wait=True, cancel_futures=True)
