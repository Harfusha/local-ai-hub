import threading
import time

import pytest

from local_ai_hub.config import ConfigError, validate_config
from local_ai_hub.laya_lifecycle import LayaSessionLifecycle, validate_idle_unload_seconds


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class FakeSession:
    def __init__(self):
        self.closed = False


def test_idle_timeout_uses_inference_completion_then_reloads_after_unload():
    clock = FakeClock()
    sessions = []
    closes = []

    def load():
        session = FakeSession()
        sessions.append(session)
        return session

    lifecycle = LayaSessionLifecycle(600, close_session=lambda session: (setattr(session, "closed", True) or closes.append(session) or True), clock=clock)
    clock.value = 50
    with lifecycle.inference_session(load) as first:
        clock.value = 900  # Runtime duration does not count as idle.
        assert lifecycle.poll_idle_unload() == "busy"
    assert lifecycle.poll_idle_unload(1499.9) == "not_idle"
    assert lifecycle.poll_idle_unload(1500) == "unloaded"
    assert first.closed is True
    with lifecycle.inference_session(load) as second:
        assert second is not first
    assert len(sessions) == 2
    assert len(closes) == 1
    assert lifecycle.poll_idle_unload(2100) == "unloaded"


@pytest.mark.parametrize("invalid_now", [float("nan"), float("inf"), float("-inf"), True, "600"])
def test_idle_unload_rejects_invalid_clock_values_without_closing_session(invalid_now):
    clock = FakeClock()
    closed = []
    lifecycle = LayaSessionLifecycle(600, close_session=lambda session: closed.append(session) or True, clock=clock)
    with lifecycle.inference_session(FakeSession):
        pass

    with pytest.raises(ValueError, match="finite monotonic timestamp"):
        lifecycle.poll_idle_unload(invalid_now)

    assert lifecycle.status["available"] is True
    assert closed == []


def test_non_finite_internal_clock_fails_closed_without_unloading_session():
    closed = []
    lifecycle = LayaSessionLifecycle(
        600,
        close_session=lambda session: closed.append(session) or True,
        clock=lambda: float("nan"),
    )
    with lifecycle.inference_session(FakeSession):
        pass

    with pytest.raises(ValueError, match="finite monotonic timestamp"):
        lifecycle.poll_idle_unload()

    assert lifecycle.status["available"] is True
    assert closed == []


@pytest.mark.parametrize(
    "invalid_time",
    [
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="infinity"),
        pytest.param(True, id="boolean"),
        pytest.param(10**10000, id="integer-overflow"),
    ],
)
def test_invalid_completion_clock_never_starts_idle_unload_timer(invalid_time):
    closed = []

    def invalid_clock():
        return invalid_time

    lifecycle = LayaSessionLifecycle(
        600, close_session=lambda session: closed.append(session) or True,
        clock=invalid_clock,
    )
    with lifecycle.inference_session(FakeSession):
        pass

    # Even an arbitrarily large valid poll timestamp cannot turn an invalid
    # inference completion time into an immediately expired idle interval.
    assert lifecycle.poll_idle_unload(1e300) == "not_idle"
    assert lifecycle.status["available"] is True
    assert closed == []


def test_completion_clock_exception_does_not_reuse_old_idle_timestamp():
    clock = FakeClock()
    closed = []

    def ticking_clock():
        if clock.value == 2:
            raise RuntimeError("clock unavailable")
        return clock.value

    lifecycle = LayaSessionLifecycle(
        10, close_session=lambda session: closed.append(session) or True,
        clock=ticking_clock,
    )
    with lifecycle.inference_session(FakeSession):
        pass
    clock.value = 1
    with lifecycle.inference_session(FakeSession):
        pass
    clock.value = 2
    with lifecycle.inference_session(FakeSession):
        pass

    assert lifecycle.poll_idle_unload(1000) == "not_idle"
    assert lifecycle.status["available"] is True
    assert closed == []


def test_concurrent_inference_shares_session_and_blocks_idle_release():
    clock = FakeClock()
    lifecycle = LayaSessionLifecycle(10, close_session=lambda _session: True, clock=clock)
    loaded = []
    entered = threading.Event()
    finish = threading.Event()

    def load():
        session = FakeSession()
        loaded.append(session)
        return session

    def inference():
        with lifecycle.inference_session(load):
            entered.set()
            finish.wait(2)

    worker = threading.Thread(target=inference)
    worker.start()
    assert entered.wait(1)
    assert lifecycle.poll_idle_unload(1000) == "busy"
    finish.set()
    worker.join(1)
    assert not worker.is_alive()
    assert lifecycle.poll_idle_unload(clock.value + 10) == "unloaded"
    assert len(loaded) == 1


def test_concurrent_waiters_share_one_failed_load_attempt():
    lifecycle = LayaSessionLifecycle(600, close_session=lambda _session: True)
    load_started = threading.Event()
    release_load = threading.Event()
    waiter_entered = threading.Event()
    load_attempts = []
    failures = []
    original_wait = lifecycle._condition.wait

    def tracked_wait(timeout=None):
        waiter_entered.set()
        return original_wait(timeout)

    lifecycle._condition.wait = tracked_wait

    def load():
        load_attempts.append(1)
        if len(load_attempts) == 1:
            load_started.set()
            assert release_load.wait(2)
            raise OSError("provider unavailable")
        return FakeSession()

    def inference():
        try:
            with lifecycle.inference_session(load):
                failures.append(None)
        except Exception as exc:
            failures.append(exc)

    first = threading.Thread(target=inference)
    second = threading.Thread(target=inference)
    first.start()
    assert load_started.wait(1)
    second.start()
    assert waiter_entered.wait(1)
    release_load.set()
    first.join(1)
    second.join(1)

    assert not first.is_alive()
    assert not second.is_alive()
    assert len(load_attempts) == 1
    assert len(failures) == 2
    assert sum(isinstance(exc, OSError) for exc in failures) == 1
    assert sum(isinstance(exc, RuntimeError) for exc in failures) == 1

    with lifecycle.inference_session(load) as later_session:
        assert isinstance(later_session, FakeSession)
    assert len(load_attempts) == 2


def test_new_inference_waits_for_in_progress_close_then_reloads_once():
    clock = FakeClock()
    closing = threading.Event()
    allow_close = threading.Event()
    loaded = []
    lifecycle = LayaSessionLifecycle(
        1,
        clock=clock,
        close_session=lambda _session: (closing.set() or allow_close.wait(2) or True),
    )

    def load():
        session = FakeSession()
        loaded.append(session)
        return session

    with lifecycle.inference_session(load):
        pass
    clock.value = 1
    releaser = threading.Thread(target=lambda: lifecycle.poll_idle_unload())
    releaser.start()
    assert closing.wait(1)
    entered = threading.Event()

    def next_inference():
        with lifecycle.inference_session(load):
            entered.set()

    requester = threading.Thread(target=next_inference)
    requester.start()
    assert not entered.wait(0.05)
    allow_close.set()
    releaser.join(1)
    requester.join(1)
    assert entered.is_set()
    assert len(loaded) == 2


def test_zero_timeout_disables_automatic_release_but_shutdown_can_close():
    clock = FakeClock()
    closed = []
    lifecycle = LayaSessionLifecycle(0, close_session=lambda session: closed.append(session) or True, clock=clock)
    with lifecycle.inference_session(FakeSession):
        pass
    clock.value = 10_000
    assert lifecycle.poll_idle_unload() == "disabled"
    assert closed == []
    assert lifecycle.shutdown() is True
    assert len(closed) == 1


def test_provider_close_error_keeps_session_and_reports_unconfirmed_release():
    clock = FakeClock()
    session = FakeSession()
    lifecycle = LayaSessionLifecycle(1, close_session=lambda _session: (_ for _ in ()).throw(OSError("device close failed")), clock=clock)
    with lifecycle.inference_session(lambda: session):
        pass
    clock.value = 1
    assert lifecycle.poll_idle_unload() == "close_failed"
    assert lifecycle.status["available"] is True
    assert lifecycle.status["last_close_error"] == "OSError"
    assert lifecycle.poll_idle_unload(100) == "close_failed"  # no retry loop
    with lifecycle.inference_session(lambda: pytest.fail("failed close retains the loaded session")) as retained:
        assert retained is session


def test_app_created_lifecycle_can_bind_one_provider_close_callback_before_first_session():
    clock = FakeClock()
    closed = []
    lifecycle = LayaSessionLifecycle(1, clock=clock)
    assert lifecycle.status["provider_close_configured"] is False

    close_provider_session = lambda session: closed.append(session) or True
    lifecycle.bind_close_session(close_provider_session)
    assert lifecycle.status["provider_close_configured"] is True
    with lifecycle.inference_session(FakeSession) as session:
        pass
    clock.value = 1
    assert lifecycle.poll_idle_unload() == "unloaded"
    assert closed == [session]
    lifecycle.bind_close_session(close_provider_session)  # Same adapter bind is idempotent.
    with pytest.raises(RuntimeError, match="already bound"):
        lifecycle.bind_close_session(lambda _session: True)


def test_shutdown_never_closes_an_inflight_session():
    entered = threading.Event()
    finish = threading.Event()
    closed = []
    lifecycle = LayaSessionLifecycle(600, close_session=lambda session: closed.append(session) or True)

    def inference():
        with lifecycle.inference_session(FakeSession):
            entered.set()
            finish.wait(2)

    worker = threading.Thread(target=inference)
    worker.start()
    assert entered.wait(1)
    assert lifecycle.shutdown(timeout_seconds=0.01) is False
    assert closed == []
    finish.set()
    worker.join(1)
    assert lifecycle.shutdown(timeout_seconds=1) is True
    assert len(closed) == 1


def test_shutdown_racing_with_load_closes_late_session_before_finishing():
    loading = threading.Event()
    finish_load = threading.Event()
    closed = []
    session = FakeSession()
    lifecycle = LayaSessionLifecycle(close_session=lambda value: closed.append(value) or True)

    def load():
        loading.set()
        finish_load.wait(2)
        return session

    request_errors = []

    def inference():
        try:
            with lifecycle.inference_session(load):
                pytest.fail("shutdown must reject the inference")
        except RuntimeError as exc:
            request_errors.append(str(exc))

    requester = threading.Thread(target=inference)
    requester.start()
    assert loading.wait(1)
    shutdown_results = []
    shutdown = threading.Thread(target=lambda: shutdown_results.append(lifecycle.shutdown(timeout_seconds=1)))
    shutdown.start()
    deadline = time.monotonic() + 1
    while not lifecycle.status["shutdown"] and time.monotonic() < deadline:
        time.sleep(0.001)
    assert lifecycle.status["shutdown"] is True
    finish_load.set()
    requester.join(1)
    shutdown.join(1)
    assert not requester.is_alive()
    assert not shutdown.is_alive()
    assert request_errors == ["Laya session lifecycle is shutting down"]
    assert shutdown_results == [True]
    assert closed == [session]
    assert lifecycle.status["available"] is False


@pytest.mark.parametrize("value", [0, 600, 86400, 1.5])
def test_lifecycle_timeout_validator_accepts_finite_controller_values(value):
    assert validate_idle_unload_seconds(value) == value


def test_config_accepts_the_fixed_ten_minute_laya_timeout():
    validate_config({"laya": {"idle_unload_seconds": 600}})


def test_configured_laya_checkpoint_is_valid_even_when_legacy_enabled_is_false(tmp_path):
    checkpoint = tmp_path / "pinned-revision"
    validate_config({"laya": {"idle_unload_seconds": 600, "runtime": {
        "enabled": False,
        "checkpoint_path": str(checkpoint),
        "revision": checkpoint.name,
        "expected_sha256": {"weights.safetensors": "a" * 64},
    }}})


def test_config_allows_service_without_a_checkpoint():
    validate_config({"laya": {"idle_unload_seconds": 600, "runtime": {
        "checkpoint_path": "", "revision": "", "expected_sha256": {},
    }}})


def test_partial_laya_checkpoint_is_rejected_without_legacy_enabled_gate(tmp_path):
    with pytest.raises(ConfigError, match="laya.runtime requires revision"):
        validate_config({"laya": {"idle_unload_seconds": 600, "runtime": {
            "enabled": False,
            "checkpoint_path": str(tmp_path / "pinned-revision"),
        }}})


@pytest.mark.parametrize("value", [0, 1.5, 599, 601, 86400])
def test_config_rejects_non_ten_minute_laya_timeouts(value):
    with pytest.raises(ConfigError, match="laya.idle_unload_seconds"):
        validate_config({"laya": {"idle_unload_seconds": value}})


@pytest.mark.parametrize("value", [-1, 86401, 10**400, float("nan"), float("inf"), float("-inf"), True, "600"])
def test_idle_unload_setting_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="0 through 86400"):
        validate_idle_unload_seconds(value)
    with pytest.raises(ConfigError, match="laya.idle_unload_seconds"):
        validate_config({"laya": {"idle_unload_seconds": value}})
