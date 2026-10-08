from __future__ import annotations

import time

from local_ai_hub.ollama import OllamaRuntime


def test_gaming_unload_requests_every_loaded_ollama_model_and_verifies_empty_set(monkeypatch):
    runtime = object.__new__(OllamaRuntime)
    runtime.config = {"ollama": {"enabled": True}}
    replies = iter([
        {"models": [{"name": "fast:latest"}, {"model": "smart:latest"}, {"name": "fast:latest"}]},
        {"done_reason": "unload"},
        {"done_reason": "unload"},
        {"models": []},
    ])
    calls = []
    deadlines = []

    def request(endpoint, payload=None, *, timeout, should_stop, deadline):
        assert should_stop is None or (callable(should_stop) and should_stop() is False)
        assert 0 < timeout <= 2.0
        assert time.monotonic() < deadline
        deadlines.append(deadline)
        calls.append((endpoint, payload))
        return next(replies)

    monkeypatch.setattr(runtime, "request", request)
    monkeypatch.setattr(runtime, "_invalidate_loaded_cache", lambda: None)

    result = runtime.unload_configured_models(timeout_seconds=2.0)

    assert result["success"] is True, result
    assert result["requested"] == ["fast:latest", "smart:latest"]
    assert result["unloaded"] == ["fast:latest", "smart:latest"]
    assert result["remaining"] == []
    assert result["verified"] is True
    assert len(set(deadlines)) == 1
    assert [endpoint for endpoint, _payload in calls] == [
        "/api/ps", "/api/generate", "/api/generate", "/api/ps",
    ]
    assert [payload for _endpoint, payload in calls[1:3]] == [
        {"model": "fast:latest", "prompt": "", "keep_alive": 0},
        {"model": "smart:latest", "prompt": "", "keep_alive": 0},
    ]
