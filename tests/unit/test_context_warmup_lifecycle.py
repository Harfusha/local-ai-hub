from __future__ import annotations

import threading
import time

from local_ai_hub.context_warmup import ContextWarmup


def _wait_for_state(warmup: ContextWarmup, key: str, expected: str) -> dict[str, object]:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        state = warmup.lifecycle_state(key)
        if state is not None and state.get("state") == expected:
            return state
        time.sleep(0.005)
    raise AssertionError(f"warmup state for {key!r} did not become {expected!r}")


def test_running_and_success_states_keep_success_cooldown() -> None:
    warmup = ContextWarmup()
    entered = threading.Event()
    release = threading.Event()
    try:
        assert warmup.submit("success", lambda: (entered.set(), release.wait(1.0), "ok")[-1])
        assert entered.wait(1.0)
        assert warmup.lifecycle_state("success")["state"] == "running"

        release.set()
        _wait_for_state(warmup, "success", "succeeded")
        assert warmup.submit("success", lambda: "duplicate") is False
    finally:
        release.set()
        warmup.close()


def test_failure_uses_short_backoff_and_can_retry(monkeypatch) -> None:
    warmup = ContextWarmup()
    monkeypatch.setattr(warmup, "_FAILURE_BACKOFF_SECONDS", 0.01)
    try:
        assert warmup.submit("failure", lambda: {"success": False})
        _wait_for_state(warmup, "failure", "failed")
        time.sleep(0.02)
        assert warmup.submit("failure", lambda: "recovered")
        _wait_for_state(warmup, "failure", "succeeded")
    finally:
        warmup.close()


def test_expired_queue_item_is_not_invoked_and_records_expired(monkeypatch) -> None:
    warmup = ContextWarmup()
    monkeypatch.setattr(warmup, "_QUEUE_TTL_SECONDS", 0.0)
    invoked = threading.Event()
    try:
        assert warmup.submit("expired", lambda: invoked.set())
        state = _wait_for_state(warmup, "expired", "expired")
        assert state["reason"] == "queue_expired"
        assert invoked.is_set() is False
        assert "expired" not in warmup._pending
    finally:
        warmup.close()


def test_enqueued_state_is_visible_and_close_expires_queued_work() -> None:
    class WorkerStub:
        def is_alive(self) -> bool:
            return True

        def join(self, timeout: float) -> None:
            return None

    warmup = ContextWarmup()
    warmup._worker = WorkerStub()
    assert warmup.submit("queued", lambda: "unused")
    assert warmup.lifecycle_state("queued")["state"] == "enqueued"

    warmup.close()

    assert warmup.lifecycle_state("queued")["state"] == "expired"
    assert "queued" not in warmup._pending


def test_lifecycle_state_history_is_bounded(monkeypatch) -> None:
    warmup = ContextWarmup()
    monkeypatch.setattr(warmup, "_RECENT_LIMIT", 3)
    with warmup._lock:
        for index in range(8):
            warmup._record_state(str(index), "succeeded", float(index))

    assert len(warmup._states) == 3
