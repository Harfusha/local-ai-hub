import json
import threading

import pytest

from local_ai_hub import client as client_module
from local_ai_hub.client import HubClient


class _ObservedEvent(threading.Event):
    def __init__(self):
        super().__init__()
        self.wait_started = threading.Event()

    def wait(self, timeout=None):
        self.wait_started.set()
        return super().wait(timeout)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(client_module, "load_config", lambda *_args, **_kwargs: {
        "server": {"port": 11435},
        "security": {"api_token": "owner-secret", "allowed_roots": [str(tmp_path)]},
    })
    instance = HubClient(auto_start=False)
    yield instance
    instance.close()


def _run_get_in_thread(client, cancel_event, results, *, auto_start=False):
    client.auto_start = auto_start
    worker = threading.Thread(
        target=lambda: results.append(
            client.get("/api/status", timeout=1.0, cancel_event=cancel_event)
        ),
        daemon=True,
    )
    worker.start()
    return worker


def _assert_cancelled(result, request_id):
    assert result["success"] is False
    assert result["error"] == "request cancelled"
    assert result["cancelled"] is True
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert result["outcome_unknown"] is True
    assert result["request_id"] == request_id


def test_get_cancellation_interrupts_snapshot_warming_retry(client, monkeypatch):
    cancel_event = _ObservedEvent()
    warming_response_sent = threading.Event()
    attempts = []
    results = []

    def open_request(_verb, _path, _body, headers, _timeout, **_options):
        attempts.append(headers["X-LocalAI-Request-ID"])
        warming_response_sent.set()
        return json.dumps({"snapshot_warming": True, "retry_after_ms": 250}).encode()

    monkeypatch.setattr(client, "_open", open_request)
    worker = _run_get_in_thread(client, cancel_event, results)
    try:
        assert warming_response_sent.wait(1)
        assert cancel_event.wait_started.wait(1), "warming retry did not enter cancellable wait"
        cancel_event.set()
        worker.join(1)
        assert not worker.is_alive(), "cancellation did not wake the warming retry delay"
    finally:
        cancel_event.set()
        worker.join(1)

    assert len(attempts) == 1
    assert len(results) == 1
    _assert_cancelled(results[0], attempts[0])


def test_get_cancellation_interrupts_transport_recovery_delay(client, monkeypatch):
    cancel_event = _ObservedEvent()
    recovery_started = threading.Event()
    attempts = []
    results = []

    def open_request(_verb, _path, _body, headers, _timeout, **_options):
        attempts.append(headers["X-LocalAI-Request-ID"])
        raise OSError("bounded transport failure")

    def ensure_server(*, timeout=None):
        recovery_started.set()
        return True

    monkeypatch.setattr(client, "_open", open_request)
    monkeypatch.setattr(client, "ensure_server", ensure_server)
    worker = _run_get_in_thread(client, cancel_event, results, auto_start=True)
    try:
        assert recovery_started.wait(1)
        assert cancel_event.wait_started.wait(1), "recovery retry did not enter cancellable wait"
        attempts_before_cancel = len(attempts)
        cancel_event.set()
        worker.join(1)
        assert not worker.is_alive(), "cancellation did not wake the recovery retry delay"
    finally:
        cancel_event.set()
        worker.join(1)

    # The initial failure and first read retry precede this recovery delay.
    # Cancellation must prevent every subsequent attempt.
    assert len(attempts) == attempts_before_cancel == 2
    assert len(results) == 1
    _assert_cancelled(results[0], attempts[0])
