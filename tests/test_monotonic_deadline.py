from __future__ import annotations

import time

import pytest

from local_ai_hub.monotonic_deadline import DeadlineExceededError, MonotonicDeadline


def test_monotonic_deadline_from_timeout():
    dl = MonotonicDeadline.from_timeout(0.1)
    assert not dl.is_expired
    assert 0.0 < dl.remaining_seconds <= 0.1
    dl.check("test_op")

    time.sleep(0.11)
    assert dl.is_expired
    assert dl.remaining_seconds == 0.0
    with pytest.raises(DeadlineExceededError, match="test_op exceeded monotonic deadline"):
        dl.check("test_op")


def test_monotonic_deadline_from_deadline():
    target = time.monotonic() + 0.05
    dl = MonotonicDeadline.from_deadline(target)
    assert not dl.is_expired
    assert dl.deadline == target

    time.sleep(0.06)
    assert dl.is_expired


def test_monotonic_deadline_infinite_timeout():
    dl = MonotonicDeadline.from_timeout(None)
    assert not dl.is_expired
    assert dl.remaining_seconds == float("inf")
    assert dl.remaining_or_default(5.0) == 5.0
    dl.check("infinite_op")


def test_monotonic_deadline_invalid_types():
    with pytest.raises(ValueError, match="timeout_seconds must be a finite float"):
        MonotonicDeadline.from_timeout("10")

    with pytest.raises(ValueError, match="timeout_seconds must be a finite float"):
        MonotonicDeadline.from_timeout(True)

    with pytest.raises(ValueError, match="deadline must be a finite float"):
        MonotonicDeadline.from_deadline("10")
