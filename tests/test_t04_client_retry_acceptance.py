from __future__ import annotations

from io import BytesIO
from urllib.error import HTTPError, URLError

from local_ai_hub import client as client_module
from local_ai_hub.client import HubClient


def _client(tmp_path) -> HubClient:
    config = tmp_path / "client.toml"
    config.write_text(
        f"[server]\nport=39123\nstate_dir='{(tmp_path / 'state').as_posix()}'\n"
        "[client]\nmax_request_timeout_seconds=5\n",
        encoding="utf-8",
    )
    return HubClient(config_path=str(config), auto_start=False)


def test_safe_get_retries_transport_failure_with_stable_request_id(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path)
    attempts: list[tuple[str, str, str]] = []

    def pooled_open(method, path, _body, headers, _timeout):
        attempts.append((method, path, headers["X-LocalAI-Request-ID"]))
        if len(attempts) == 1:
            raise URLError("temporary disconnect")
        return b'{"success":true}'

    monkeypatch.setattr(client, "_pooled_open", pooled_open)

    assert client.get("/api/status", timeout=1) == {"success": True}
    assert [attempt[:2] for attempt in attempts] == [
        ("GET", "/api/status"),
        ("GET", "/api/status"),
    ]
    assert attempts[0][2] == attempts[1][2]


def test_unsafe_post_is_not_replayed_after_transport_failure(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path)
    client.auto_start = True
    attempts: list[str] = []
    starts: list[float | None] = []

    def pooled_open(_method, _path, _body, headers, _timeout):
        attempts.append(headers["X-LocalAI-Request-ID"])
        raise URLError("connection lost after write")

    monkeypatch.setattr(client, "_pooled_open", pooled_open)
    monkeypatch.setattr(client, "ensure_server", lambda timeout=None: starts.append(timeout) or True)

    result = client.post("/api/command", {"command": "echo bounded"}, timeout=1)

    assert len(attempts) == 1
    assert starts == []
    assert result["outcome_unknown"] is True
    assert result["request_id"] == attempts[0]


def test_auto_start_retries_pre_send_mutation_failure_with_same_request_id(
    tmp_path, monkeypatch
) -> None:
    client = _client(tmp_path)
    client.auto_start = True
    attempts: list[str] = []
    starts: list[float | None] = []

    def pooled_open(_method, _path, _body, headers, _timeout):
        attempts.append(headers["X-LocalAI-Request-ID"])
        if len(attempts) == 1:
            raise client_module._TransportFailure(
                OSError("connection refused before write"), request_not_sent=True
            )
        return b'{"success":true}'

    monkeypatch.setattr(client, "_pooled_open", pooled_open)
    monkeypatch.setattr(client, "ensure_server", lambda timeout=None: starts.append(timeout) or True)

    result = client.request(
        "/api/command",
        {"command": "echo bounded"},
        timeout=1,
        replay_safe=False,
        request_id="explicit-false",
    )

    assert attempts == ["explicit-false", "explicit-false"]
    assert len(starts) == 1
    assert result == {"success": True}


def test_pre_send_retry_with_ambiguous_failure_keeps_unknown_and_retried(
    tmp_path, monkeypatch
) -> None:
    client = _client(tmp_path)
    client.auto_start = True
    attempts: list[str] = []
    starts: list[float | None] = []

    def pooled_open(_method, _path, _body, headers, _timeout):
        attempts.append(headers["X-LocalAI-Request-ID"])
        if len(attempts) == 1:
            raise client_module._TransportFailure(
                OSError("connection refused before write"), request_not_sent=True
            )
        raise client_module._TransportFailure(
            OSError("connection lost after write"), request_not_sent=False
        )

    monkeypatch.setattr(client, "_pooled_open", pooled_open)
    monkeypatch.setattr(client, "ensure_server", lambda timeout=None: starts.append(timeout) or True)

    result = client.post(
        "/api/command",
        {"command": "echo bounded"},
        timeout=1,
        request_id="explicit-ambiguous-retry",
    )

    assert attempts == ["explicit-ambiguous-retry", "explicit-ambiguous-retry"]
    assert len(starts) == 1
    assert result["outcome_unknown"] is True
    assert result.get("request_not_sent") is not True
    assert result["retried"] is True
    assert result["request_id"] == "explicit-ambiguous-retry"


def test_pre_send_retry_with_invalid_response_keeps_unknown_and_retried(
    tmp_path, monkeypatch
) -> None:
    client = _client(tmp_path)
    client.auto_start = True
    attempts: list[str] = []

    def pooled_open(_method, _path, _body, headers, _timeout):
        attempts.append(headers["X-LocalAI-Request-ID"])
        if len(attempts) == 1:
            raise client_module._TransportFailure(
                OSError("connection refused before write"), request_not_sent=True
            )
        return b"not-json"

    monkeypatch.setattr(client, "_pooled_open", pooled_open)
    monkeypatch.setattr(client, "ensure_server", lambda timeout=None: True)

    result = client.post(
        "/api/command",
        {"command": "echo bounded"},
        timeout=1,
        request_id="explicit-invalid-retry",
    )

    assert attempts == ["explicit-invalid-retry", "explicit-invalid-retry"]
    assert result["outcome_unknown"] is True
    assert result.get("request_not_sent") is not True
    assert result["retried"] is True
    assert result["request_id"] == "explicit-invalid-retry"


def test_explicit_replay_safe_false_does_not_poll_in_progress_mutation(
    tmp_path, monkeypatch
) -> None:
    client = _client(tmp_path)
    attempts: list[str] = []

    def pooled_open(_method, _path, _body, headers, _timeout):
        attempts.append(headers["X-LocalAI-Request-ID"])
        raise HTTPError(
            "/api/command",
            503,
            "in progress",
            {},
            BytesIO(b'{"success":false,"in_progress":true,"retryable":true}'),
        )

    monkeypatch.setattr(client, "_pooled_open", pooled_open)

    result = client.request(
        "/api/command",
        {"command": "echo bounded"},
        timeout=1,
        replay_safe=False,
        request_id="explicit-false-in-progress",
    )

    assert attempts == ["explicit-false-in-progress"]
    assert result["status_code"] == 503
    assert result["in_progress"] is True
    assert result["retryable"] is True


def test_replay_safe_post_does_not_retry_terminal_503(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path)
    attempts: list[str] = []

    def pooled_open(_method, _path, _body, headers, _timeout):
        attempts.append(headers["X-LocalAI-Request-ID"])
        raise HTTPError(
            "/api/repo/complexity",
            503,
            "temporarily unavailable",
            {},
            BytesIO(b'{"success":false,"error":"temporarily unavailable"}'),
        )

    monkeypatch.setattr(client, "_pooled_open", pooled_open)

    result = client.request(
        "/api/repo/complexity",
        {"root": "repo"},
        timeout=1,
        replay_safe=True,
        request_id="terminal-503",
    )

    assert attempts == ["terminal-503"]
    assert result["status_code"] == 503
    assert result["error"] == "temporarily unavailable"
    assert result["retryable"] is True
    assert "in_progress" not in result


def test_safe_post_restart_retry_waits_for_terminal_response_within_deadline(
    tmp_path, monkeypatch
) -> None:
    client = _client(tmp_path)
    client.auto_start = True
    now = [100.0]
    attempts: list[tuple[str, bytes, str, float]] = []
    startup_timeouts: list[float | None] = []
    sleeps: list[float] = []

    def monotonic() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    def ensure_server(*, timeout=None) -> bool:
        startup_timeouts.append(timeout)
        now[0] += 0.2
        return True

    def pooled_open(_method, _path, body, headers, timeout):
        attempts.append((body.decode("utf-8"), body, headers["X-LocalAI-Request-ID"], timeout))
        now[0] += 0.1
        if len(attempts) == 1:
            raise URLError("hub restarted before response")
        if len(attempts) == 2:
            raise HTTPError(
                "/api/repo/complexity",
                503,
                "in progress",
                {},
                BytesIO(
                    b'{"success":false,"in_progress":true,"retryable":true,'
                    b'"retry_after_seconds":0.15}'
                ),
            )
        return b'{"success":true}'

    monkeypatch.setattr(client_module.time, "monotonic", monotonic)
    monkeypatch.setattr(client_module.time, "sleep", sleep)
    monkeypatch.setattr(client, "ensure_server", ensure_server)
    monkeypatch.setattr(client, "_pooled_open", pooled_open)

    result = client.post(
        "/api/repo/complexity",
        {"root": "repo"},
        timeout=1.0,
        request_id="stable-safe-retry",
    )

    assert result == {"success": True}
    assert len(attempts) == 3
    assert all(item[1] == attempts[0][1] for item in attempts)
    assert all(item[2] == "stable-safe-retry" for item in attempts)
    assert 0.89 <= startup_timeouts[0] <= 0.91
    assert all(0 < item[3] <= 1.0 for item in attempts)
    assert sleeps == [0.15]
    assert now[0] <= 101.0
