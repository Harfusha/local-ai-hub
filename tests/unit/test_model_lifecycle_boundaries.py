from __future__ import annotations

import math

import pytest

from local_ai_hub import model_lifecycle


class FakeLock:
    def __init__(self, name: str, events: list[tuple[object, ...]], result: bool = True):
        self.name = name
        self.events = events
        self.result = result

    def acquire(self, *, timeout: float) -> bool:
        self.events.append(("acquire", self.name, timeout))
        return self.result

    def release(self) -> None:
        self.events.append(("release", self.name))


@pytest.mark.parametrize(
    "timeout",
    [None, True, False, "1", object(), float("nan"), float("inf"), -0.1, 10**400],
)
def test_invalid_timeouts_raise_before_touching_locks(timeout: object) -> None:
    events: list[tuple[object, ...]] = []
    lock = FakeLock("only", events)
    with pytest.raises(ValueError):
        with model_lifecycle.acquire_locks((lock,), timeout):  # type: ignore[arg-type]
            pytest.fail("invalid timeout must not enter the lock context")
    assert events == []


def test_duplicate_locks_are_acquired_once_and_released_in_reverse_after_body_error() -> None:
    events: list[tuple[object, ...]] = []
    first = FakeLock("first", events)
    second = FakeLock("second", events)

    with pytest.raises(RuntimeError, match="body failed"):
        with model_lifecycle.acquire_locks((first, second, first, second), 0):
            raise RuntimeError("body failed")

    assert [event[:2] for event in events] == [
        ("acquire", "first"),
        ("acquire", "second"),
        ("release", "second"),
        ("release", "first"),
    ]
    assert events[0][2] == 0


def test_acquisition_failure_yields_false_and_releases_each_held_lock_once() -> None:
    events: list[tuple[object, ...]] = []
    first = FakeLock("first", events)
    second = FakeLock("second", events, result=False)

    with model_lifecycle.acquire_locks((first, second, first), 1) as acquired:
        assert acquired is False

    assert [event[:2] for event in events] == [
        ("acquire", "first"),
        ("acquire", "second"),
        ("release", "first"),
    ]


def test_large_finite_timeout_is_clamped_for_lock_api() -> None:
    events: list[tuple[object, ...]] = []
    lock = FakeLock("only", events, result=False)

    with model_lifecycle.acquire_locks((lock,), 1e300) as acquired:
        assert acquired is False

    assert 0 < events[0][2] <= model_lifecycle.threading.TIMEOUT_MAX
    assert math.isfinite(events[0][2])


def test_untrackable_cuda_owner_is_rejected_before_factory_call() -> None:
    factory_calls: list[bool] = []

    with pytest.raises(TypeError):
        model_lifecycle.load_model(
            object(), uses_cuda=True, factory=lambda: factory_calls.append(True)
        )

    assert factory_calls == []


def test_factory_failure_rolls_back_only_a_new_owner_registration() -> None:
    class Owner:
        pass

    owner = Owner()
    observed_tracking: list[bool] = []

    def failing_factory() -> object:
        observed_tracking.append(owner in model_lifecycle._CUDA_MODELS)
        raise RuntimeError("factory failed")

    try:
        with pytest.raises(RuntimeError, match="factory failed"):
            model_lifecycle.load_model(owner, uses_cuda=True, factory=failing_factory)
        assert observed_tracking == [True]
        assert owner not in model_lifecycle._CUDA_MODELS

        model_lifecycle._CUDA_MODELS.add(owner)
        with pytest.raises(RuntimeError, match="factory failed"):
            model_lifecycle.load_model(owner, uses_cuda=True, factory=failing_factory)
        assert observed_tracking == [True, True]
        assert owner in model_lifecycle._CUDA_MODELS
    finally:
        model_lifecycle._CUDA_MODELS.discard(owner)
