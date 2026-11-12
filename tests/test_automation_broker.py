from __future__ import annotations

import threading
import pytest

from local_ai_hub.automation import AutomationBroker, TargetPolicy


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_target_policy_rejects_explicit_zero_port_in_rules(scheme):
    with pytest.raises(ValueError):
        TargetPolicy([f"{scheme}://localhost:0/"])


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_target_policy_rejects_explicit_zero_port_in_candidate(scheme):
    policy = TargetPolicy([f"{scheme}://localhost/"])

    assert policy.allows(f"{scheme}://localhost:0/") is False


class Backend:
    def __init__(self):
        self.calls = []
        self.closed = False
        self.error = None
        self.entered = threading.Event()
        self.release = None

    def execute(self, request, timeout):
        self.calls.append(request)
        self.entered.set()
        if self.release:
            assert self.release.wait(3)
        if self.error:
            raise self.error
        return {"url": "http://localhost:8765/", "text": "fixture"}

    def close(self):
        self.closed = True


@pytest.fixture
def setup(tmp_path):
    made = []
    clock = [100.0]

    def factory(mode, config, request, policy):
        backend = Backend()
        made.append(backend)
        return backend

    broker = AutomationBroker({"enabled": True, "allowed_targets": ["http://localhost:8765/"],
                               "max_sessions": 2, "session_ttl_seconds": 10},
                              backend_factory=factory, clock=lambda: clock[0])
    yield broker, made, clock, str(tmp_path)
    broker.close()


def call(setup, request, owner="task-one"):
    return setup[0].execute(root=setup[3], task_id=owner, request=request)


def opened(setup, mode="isolated"):
    result = call(setup, {"op": "open", "mode": mode, "url": "http://localhost:8765/"})
    assert result["success"], result
    return result["automation"]


def act(session, **kwargs):
    return {"op": "act", "session_id": session["session_id"], "session_key": session["session_key"],
            "request_id": "request-one", "command": "snapshot", **kwargs}


@pytest.mark.parametrize("url", ["http://localhost:8766/", "https://localhost:8765/", "http://localhost.evil:8765/",
                                  "http://user@localhost:8765/", "file:///tmp/a", "http://localhost:8765/../private",
                                  "http://localhost:8765/%2e%2e/private", " http://localhost:8765/",
                                  "http://localhost:8765/\\private"])
def test_target_policy_rejects_noncanonical_or_foreign_targets(url):
    assert not TargetPolicy(["http://localhost:8765/app"]).allows(url)


def test_policy_port_and_path_boundaries():
    policy = TargetPolicy(["http://localhost:8765/app"])
    assert policy.allows("http://localhost:8765/app")
    assert policy.allows("http://localhost:8765/app/page?q=1")
    assert not policy.allows("http://localhost:8765/application")
    assert TargetPolicy(["https://example.test/"]).allows("https://example.test:443/x")
    assert not TargetPolicy([]).allows("https://example.test/")


@pytest.mark.parametrize("rule", ["*", "https://*.test/", "https://example.test/?q=1", "http://user@example.test/", 12])
def test_bad_policy_rules_reject(rule):
    with pytest.raises(ValueError):
        TargetPolicy([rule])


def test_disabled_and_empty_allowlist_prevent_backend_start(tmp_path):
    def factory(*args):
        pytest.fail("must not start backend")
    for config in ({}, {"enabled": True, "allowed_targets": []}):
        broker = AutomationBroker(config, backend_factory=factory)
        assert not broker.execute(root=str(tmp_path), task_id="t", request={"op": "open", "mode": "isolated", "url": "http://localhost/"})["success"]


def test_owner_root_and_key_are_exact(setup, tmp_path):
    session = opened(setup)
    assert not call(setup, act(session), owner="task-two")["success"]
    assert not call(setup, act(session, session_key="wrong"))["success"]
    other = tmp_path / "other"
    other.mkdir()
    assert not setup[0].execute(root=str(other), task_id="task-one", request=act(session))["success"]
    assert setup[1][0].calls == []
    assert call(setup, act(session))["success"]


def test_duplicate_mutation_does_not_run_twice_and_conflict_rejects(setup):
    session = opened(setup)
    request = act(session, command="click", selector="#submit")
    first = call(setup, request)
    assert call(setup, request) == first
    assert len(setup[1][0].calls) == 1
    assert not call(setup, {**request, "selector": "#other"})["success"]


def test_expiry_releases_backend_and_capacity(setup):
    opened(setup)
    setup[2][0] += 11
    opened(setup)
    assert setup[1][0].closed


def test_capacity_and_personal_profile_are_exclusive(setup):
    opened(setup, "extension")
    assert not call(setup, {"op": "open", "mode": "extension", "url": "http://localhost:8765/"})["success"]
    opened(setup)
    assert not call(setup, {"op": "open", "mode": "isolated", "url": "http://localhost:8765/"})["success"]


def test_timeout_fences_session_without_retry(setup):
    session = opened(setup)
    setup[1][0].error = TimeoutError()
    result = call(setup, act(session, command="click", selector="#pay"))
    assert result["outcome_unknown"] is True
    assert result["retryable"] is False
    assert not call(setup, act(session, request_id="different"))["success"]
    assert len(setup[1][0].calls) == 1
    assert setup[1][0].closed


def test_same_session_busy_but_independent_session_can_progress(setup):
    first, second = opened(setup), opened(setup)
    backend = setup[1][0]
    backend.release = threading.Event()
    result = []
    worker = threading.Thread(target=lambda: result.append(call(setup, act(first))))
    worker.start()
    try:
        assert backend.entered.wait(2)
        assert call(setup, act(first, request_id="other"))["error_code"] == "session_busy"
        assert call(setup, act(second))["success"]
    finally:
        backend.release.set()
        worker.join(3)
    assert result[0]["success"]


@pytest.mark.parametrize("payload", [{"op": "open", "mode": "isolated", "url": "http://localhost:8765/", "command_line": "evil"},
                                     {"op": "open", "mode": "vm", "url": "http://localhost:8765/"},
                                     {"op": "open", "mode": "isolated", "url": "http://localhost:8765/", "timeout_seconds": True}])
def test_malformed_requests_fail_before_backend(setup, payload):
    assert not call(setup, payload)["success"]
    assert setup[1] == []


def test_arbitrary_code_and_files_are_not_implicit_capabilities(setup):
    session = opened(setup)
    assert not call(setup, act(session, command="evaluate", code="fetch('http://evil')"))["success"]
    assert not call(setup, act(session, command="upload", path="C:/secret"))["success"]
    assert setup[1][0].calls == []


def test_shutdown_fences_and_cleans_inflight_session(setup):
    session = opened(setup)
    backend = setup[1][0]
    backend.release = threading.Event()
    worker = threading.Thread(target=lambda: call(setup, act(session)))
    worker.start()
    assert backend.entered.wait(2)
    with pytest.raises(TimeoutError):
        setup[0].close()
    backend.release.set()
    worker.join(3)
    assert backend.closed
    assert not setup[0].sessions


def test_failed_cleanup_retains_capacity_until_cleanup_succeeds(setup):
    session = opened(setup)
    backend = setup[1][0]
    original = backend.close
    backend.close = lambda: (_ for _ in ()).throw(OSError("busy"))
    result = call(setup, {"op": "close", "session_id": session["session_id"], "session_key": session["session_key"]})
    assert result["success"] is False
    assert session["session_id"] in setup[0].sessions
    backend.close = original
    result = call(setup, {"op": "close", "session_id": session["session_id"], "session_key": session["session_key"]})
    assert result["success"]


def test_close_runs_backend_cleanup_without_broker_lock(setup):
    session = opened(setup)
    broker = setup[0]
    backend = setup[1][0]
    original_close = backend.close
    lock_available_during_close = []

    def close_with_lock_probe():
        acquired = threading.Event()

        def acquire_broker_lock():
            with broker.lock:
                acquired.set()

        probe = threading.Thread(target=acquire_broker_lock)
        probe.start()
        lock_available_during_close.append(acquired.wait(1))
        probe.join(1)
        original_close()

    backend.close = close_with_lock_probe
    try:
        result = call(setup, {"op": "close", "session_id": session["session_id"], "session_key": session["session_key"]})
    finally:
        backend.close = original_close

    assert result["success"]
    assert lock_available_during_close == [True]


def test_shutdown_cancels_busy_backend_without_broker_lock(setup):
    broker, backends = setup[0], setup[1]
    session = opened(setup)
    state = broker.sessions[session["session_id"]]
    lock_held = threading.Event()
    release_lock = threading.Event()
    holder_done = threading.Event()
    lock_available_during_cancel = []

    def hold_session_lock():
        with state.lock:
            lock_held.set()
            assert release_lock.wait(3)
            holder_done.set()

    holder = threading.Thread(target=hold_session_lock)
    holder.start()
    assert lock_held.wait(1)

    def cancel_with_lock_probe():
        acquired = threading.Event()

        def acquire_broker_lock():
            with broker.lock:
                acquired.set()

        probe = threading.Thread(target=acquire_broker_lock)
        probe.start()
        lock_available_during_cancel.append(acquired.wait(1))
        release_lock.set()
        probe.join(1)

    backends[0].cancel = cancel_with_lock_probe
    try:
        with pytest.raises(TimeoutError, match="automation operations are cancelling"):
            broker.close()
    finally:
        release_lock.set()
        holder.join(1)

    assert holder_done.is_set()
    assert not holder.is_alive()
    assert lock_available_during_cancel == [True]


def test_shutdown_waits_for_cancel_before_backend_close(setup):
    broker = setup[0]
    session = opened(setup)
    backend = setup[1][0]
    state = broker.sessions[session["session_id"]]
    operation_ready = threading.Event()
    finish_operation = threading.Event()
    drop_entered = threading.Event()
    drop_finished = threading.Event()
    cancel_started = threading.Event()
    finish_cancel = threading.Event()
    cancel_finished = threading.Event()
    close_before_cancel = []
    original_close = backend.close

    def close_with_order_probe():
        close_before_cancel.append(not cancel_finished.is_set())
        original_close()

    def cancel_with_gate():
        cancel_started.set()
        assert finish_cancel.wait(3)
        cancel_finished.set()

    backend.close = close_with_order_probe
    backend.cancel = cancel_with_gate

    def finish_active_operation():
        with state.lock:
            operation_ready.set()
            assert finish_operation.wait(3)
            drop_entered.set()
            broker._drop(session["session_id"], state)
            drop_finished.set()

    worker = threading.Thread(target=finish_active_operation)
    worker.start()
    assert operation_ready.wait(1)
    shutdown_errors = []

    def shutdown():
        try:
            broker.close()
        except Exception as exc:
            shutdown_errors.append(exc)

    closer = threading.Thread(target=shutdown)
    closer.start()
    assert cancel_started.wait(1)
    finish_operation.set()
    assert drop_entered.wait(1)
    try:
        assert not drop_finished.wait(0.1)
    finally:
        finish_cancel.set()

    worker.join(1)
    closer.join(2)
    assert not worker.is_alive()
    assert not closer.is_alive()
    assert drop_finished.is_set()
    assert close_before_cancel == [False]
    assert any(isinstance(exc, TimeoutError) for exc in shutdown_errors)


def test_shutdown_cancel_failure_releases_claimed_session_locks(setup):
    broker = setup[0]
    first = opened(setup)
    second = opened(setup)
    busy = broker.sessions[first["session_id"]]
    idle = broker.sessions[second["session_id"]]
    assert busy.lock.acquire(blocking=False)

    def fail_cancel():
        raise RuntimeError("cancel failed")

    setup[1][0].cancel = fail_cancel
    try:
        with pytest.raises(RuntimeError, match="cancel failed"):
            broker.close()
        assert idle.backend_closed
        assert setup[1][1].closed
        assert idle.lock.acquire(blocking=False)
        idle.lock.release()
    finally:
        busy.lock.release()


def test_desktop_window_is_leased_to_one_session(setup):
    request = {"op": "open", "mode": "desktop", "application": "editor", "window_id": 123}
    assert call(setup, request)["success"]
    denied = call(setup, request, owner="task-two")
    assert denied["error_code"] == "window_busy"
    assert len(setup[1]) == 1


def test_active_execute_waits_for_shutdown_cancel_before_backend_close(setup):
    broker = setup[0]
    session = opened(setup)
    backend = setup[1][0]
    backend.release = threading.Event()
    cancel_started = threading.Event()
    finish_cancel = threading.Event()
    cancel_finished = threading.Event()
    operation_finished = threading.Event()
    close_before_cancel = []
    original_close = backend.close

    def cancel_with_gate():
        cancel_started.set()
        assert finish_cancel.wait(3)
        cancel_finished.set()

    def close_with_order_probe():
        close_before_cancel.append(not cancel_finished.is_set())
        original_close()

    backend.cancel = cancel_with_gate
    backend.close = close_with_order_probe
    operation_result = []

    def active_operation():
        try:
            operation_result.append(call(setup, act(session)))
        finally:
            operation_finished.set()

    operation = threading.Thread(target=active_operation)
    operation.start()
    assert backend.entered.wait(1)

    shutdown_errors = []

    def shutdown():
        try:
            broker.close()
        except Exception as exc:
            shutdown_errors.append(exc)

    closer = threading.Thread(target=shutdown)
    closer.start()
    assert cancel_started.wait(1)
    backend.release.set()
    assert not operation_finished.wait(0.1)
    finish_cancel.set()
    operation.join(2)
    closer.join(2)

    assert not operation.is_alive()
    assert not closer.is_alive()
    assert operation_result and operation_result[0]["success"]
    assert len(shutdown_errors) == 1 and isinstance(shutdown_errors[0], TimeoutError)
    assert close_before_cancel == [False]
    assert backend.closed
