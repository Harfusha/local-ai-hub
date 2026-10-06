from __future__ import annotations

from local_ai_hub.client import HubClient


def _client(tmp_path):
    config = tmp_path / "client.toml"
    state = (tmp_path / "state").as_posix()
    config.write_text(
        f"[server]\nport=39123\nstate_dir='{state}'\n"
        "[client]\nmax_request_timeout_seconds=5\n",
        encoding="utf-8",
    )
    return HubClient(config_path=str(config), auto_start=False)


def test_get_malformed_json_returns_complete_retryable_invalid_response(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls = []

    def malformed(*args, **kwargs):
        calls.append((args, kwargs))
        return b"{"

    monkeypatch.setattr(client, "_pooled_open", malformed)
    result = client.get("/api/status")

    assert len(calls) == 1
    assert result == {
        "success": False,
        "error": "invalid JSON response",
        "status_code": 502,
        "request_id": result["request_id"],
        "retryable": True,
        "terminal": False,
    }
    assert result.get("outcome_unknown", False) is False


def test_ambiguous_mutating_post_malformed_json_is_unknown_without_replay(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls = []
    request_id = "explicit-mutation-id"

    def malformed(method, path, body, headers, timeout):
        calls.append((method, path, headers, body))
        return b"{"

    monkeypatch.setattr(client, "_pooled_open", malformed)
    result = client.post("/api/command", {"command": "perform-write"}, request_id=request_id)

    assert len(calls) == 1
    assert calls[0][2]["X-LocalAI-Request-ID"] == request_id
    assert result == {
        "success": False,
        "error": "invalid JSON response",
        "status_code": 502,
        "request_id": request_id,
        "outcome_unknown": True,
        "retryable": False,
        "terminal": True,
    }


def test_safe_post_retry_malformed_json_keeps_safe_response_classification(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls = []
    request_id = "explicit-safe-id"

    def transient_then_malformed(method, path, body, headers, timeout):
        calls.append((method, path, headers, body))
        if len(calls) == 1:
            raise OSError("transient transport failure")
        return b"{"

    monkeypatch.setattr(client, "_pooled_open", transient_then_malformed)
    result = client.post("/api/memory/get", {"key": "alpha"}, request_id=request_id)

    assert len(calls) == 2
    assert [call[2]["X-LocalAI-Request-ID"] for call in calls] == [request_id, request_id]
    assert result == {
        "success": False,
        "error": "invalid JSON response",
        "status_code": 502,
        "request_id": request_id,
        "retryable": True,
        "terminal": False,
    }
    assert result.get("outcome_unknown", False) is False
