import urllib.error

from local_ai_hub.agent_incidents import _send_incident_webhooks


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
