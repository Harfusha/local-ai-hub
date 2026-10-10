from __future__ import annotations

import json

from local_ai_hub import client as client_module
from local_ai_hub.client import HubClient


def _client(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        "[server]\nport=39123\nstate_dir='" + (tmp_path / "state").as_posix() + "'\n"
        "[client]\nmax_request_timeout_seconds=5\n",
        encoding="utf-8",
    )
    return HubClient(config_path=str(config), auto_start=True)


def test_mutating_post_retries_only_after_proven_pre_send_refusal(tmp_path, monkeypatch):
    client = _client(tmp_path)
    attempts = []
    starts = []

    def pooled_open(method, path, body, headers, timeout):
        attempts.append((method, path, bytes(body), dict(headers)))
        if len(attempts) == 1:
            raise client_module._TransportFailure(
                ConnectionRefusedError("offline"), request_not_sent=True
            )
        return b'{"success":true}'

    monkeypatch.setattr(client, "_pooled_open", pooled_open)
    monkeypatch.setattr(client, "ensure_server", lambda timeout=None: starts.append(timeout) or True)

    result = client.post("/api/tasks/checkpoint", {"task_id": "t1"}, request_id="stable-id")

    assert result == {"success": True}
    assert len(starts) == 1
    assert len(attempts) == 2
    assert attempts[0][2:] == attempts[1][2:]
    assert attempts[0][3]["X-LocalAI-Request-ID"] == "stable-id"


def test_mutating_post_never_retries_when_write_may_have_started(tmp_path, monkeypatch):
    client = _client(tmp_path)
    attempts = []
    starts = []

    def pooled_open(method, path, body, headers, timeout):
        attempts.append((method, path, bytes(body), dict(headers)))
        raise client_module._TransportFailure(OSError("connection reset"), request_not_sent=False)

    monkeypatch.setattr(client, "_pooled_open", pooled_open)
    monkeypatch.setattr(client, "ensure_server", lambda timeout=None: starts.append(timeout) or True)

    result = client.post("/api/tasks/checkpoint", {"task_id": "t1"}, request_id="stable-id")

    assert len(attempts) == 1
    assert starts == []
    assert result["outcome_unknown"] is True
    assert result["terminal"] is True
    assert result["retryable"] is False


def test_pre_send_failure_without_startup_is_terminal_non_retryable(tmp_path, monkeypatch):
    client = _client(tmp_path)

    def pooled_open(*_args, **_kwargs):
        raise client_module._TransportFailure(
            ConnectionRefusedError("offline"), request_not_sent=True
        )

    monkeypatch.setattr(
        client,
        "_pooled_open",
        pooled_open,
    )
    monkeypatch.setattr(client, "ensure_server", lambda timeout=None: False)

    result = client.post("/api/tasks/checkpoint", {"task_id": "t1"}, request_id="stable-id")

    assert result["request_not_sent"] is True
    assert result["outcome_unknown"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False


def test_failed_retry_after_startup_is_reported_as_uncertain(tmp_path, monkeypatch):
    client = _client(tmp_path)
    attempts = []

    def pooled_open(*_args):
        attempts.append(True)
        if len(attempts) == 1:
            raise client_module._TransportFailure(
                ConnectionRefusedError("offline"), request_not_sent=True
            )
        return b"not-json"

    monkeypatch.setattr(client, "_pooled_open", pooled_open)
    monkeypatch.setattr(client, "ensure_server", lambda timeout=None: True)

    result = client.post("/api/tasks/checkpoint", {"task_id": "t1"}, request_id="stable-id")

    assert result["outcome_unknown"] is True
    assert result.get("request_not_sent") is not True
    assert result["retried"] is True


def test_get_non_object_json_stays_a_complete_client_error(tmp_path, monkeypatch):
    client = _client(tmp_path)
    client.auto_start = False
    monkeypatch.setattr(client, "_pooled_open", lambda *_args, **_kwargs: json.dumps([]).encode())

    result = client.get("/health")

    assert result["status_code"] == 502
    assert result["retryable"] is True
    assert result["terminal"] is False


def test_startup_probe_distinguishes_liveness_from_readiness(tmp_path, monkeypatch):
    from urllib.error import HTTPError

    client = _client(tmp_path)
    requested_urls = []

    def not_ready(request, timeout):
        requested_urls.append(request.full_url)
        raise HTTPError(request.full_url, 503, "not ready", {}, None)

    monkeypatch.setattr(client_module, "urlopen", not_ready)

    assert client._online(timeout=1) is False
    assert requested_urls == [f"{client.base_url}/ready"]
