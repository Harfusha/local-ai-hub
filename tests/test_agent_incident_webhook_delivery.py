import urllib.error
import threading

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_incidents import (
    IncidentStore,
    _IncidentWebhookDispatcher,
    _MAX_INCIDENT_WEBHOOK_URL_CHARS,
    _MAX_INCIDENT_WEBHOOK_URLS,
    _send_incident_webhooks,
)


def test_webhook_delivery_failure_is_logged_without_request_details(monkeypatch, caplog):
    webhook_url = "https://hooks.example/private-token"
    payload = b"private incident payload"

    def fail_urlopen(request, timeout):
        raise urllib.error.URLError("private response detail")

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)

    with caplog.at_level("WARNING", logger="local_ai_hub.agent_incidents"):
        _send_incident_webhooks([webhook_url], payload)

    assert "URLError" in caplog.text
    assert webhook_url not in caplog.text
    assert "private incident payload" not in caplog.text
    assert "private response detail" not in caplog.text


def test_webhook_dispatcher_bounds_pending_jobs_and_uses_one_worker():
    started = threading.Event()
    release = threading.Event()
    delivered = []
    worker_ids = set()

    def sender(urls, payload):
        worker_ids.add(threading.get_ident())
        delivered.append((urls, payload))
        if payload == b"first":
            started.set()
            release.wait()

    dispatcher = _IncidentWebhookDispatcher(max_pending=1, sender=sender)
    try:
        assert dispatcher.submit(["https://hooks.example/one"], b"first")
        assert started.wait(1)
        assert dispatcher.submit(["https://hooks.example/one"], b"second")
        assert not dispatcher.submit(["https://hooks.example/one"], b"third")
    finally:
        release.set()
        assert dispatcher.close(timeout=2)

    assert [payload for _, payload in delivered] == [b"first", b"second"]
    assert len(worker_ids) == 1


def test_webhook_dispatcher_rejects_payload_over_bound():
    dispatcher = _IncidentWebhookDispatcher(max_pending=1, max_payload_bytes=4)
    try:
        assert not dispatcher.submit(["https://hooks.example/one"], b"oversized")
    finally:
        assert dispatcher.close(timeout=1)


def test_incident_webhook_registration_is_bounded(tmp_path):
    incidents = IncidentStore(AgentStateStore(tmp_path / "agent_state.sqlite3"))

    for index in range(_MAX_INCIDENT_WEBHOOK_URLS):
        assert incidents.register_webhook(f"https://hooks.example/{index}")

    assert incidents.register_webhook("https://hooks.example/0")
    assert not incidents.register_webhook("https://hooks.example/overflow")
    assert not incidents.register_webhook("x" * (_MAX_INCIDENT_WEBHOOK_URL_CHARS + 1))
    assert len(incidents.webhook_urls) == _MAX_INCIDENT_WEBHOOK_URLS
