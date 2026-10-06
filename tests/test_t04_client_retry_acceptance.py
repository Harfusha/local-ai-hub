from __future__ import annotations

from urllib.error import URLError

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
    attempts: list[str] = []

    def pooled_open(_method, _path, _body, headers, _timeout):
        attempts.append(headers["X-LocalAI-Request-ID"])
        raise URLError("connection lost after write")

    monkeypatch.setattr(client, "_pooled_open", pooled_open)

    result = client.post("/api/command", {"command": "echo bounded"}, timeout=1)

    assert len(attempts) == 1
    assert result["outcome_unknown"] is True
    assert result["request_id"] == attempts[0]
