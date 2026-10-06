from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from local_ai_hub.ollama import OllamaRuntime


def _runtime(tmp_path: Path, *, ollama_enabled: bool = True) -> OllamaRuntime:
    return OllamaRuntime({
        "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434", "request_timeout_seconds": 1.0},
        "ollama": {"enabled": ollama_enabled, "request_attempts": 1},
        "models": {"fast_code": "configured-fast", "heavy_code": "configured-heavy"},
        "ollama_subagents": {"profiles": {"drafter": {"model": "configured-subagent"}}},
        "llama_cpp": {
            "fallback_to_ollama": True,
            "models": {} if ollama_enabled else {"adapter-fast": {"served_model": "served-fast"}},
        },
    })


def test_pause_unloads_only_configured_resident_models_with_empty_prompt(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    requests = []

    def request(endpoint, payload=None, timeout=None):
        requests.append((endpoint, payload, timeout))
        if endpoint == "/api/ps":
            return {"models": [
                {"name": "configured-fast"},
                {"name": "configured-subagent"},
                {"name": "unconfigured-external"},
            ]}
        assert endpoint == "/api/generate"
        return {"done": True, "done_reason": "unload"}

    monkeypatch.setattr(runtime, "request", request)
    monkeypatch.setattr(runtime, "load_model", lambda *_a, **_k: pytest.fail("pause must not load a model"))
    monkeypatch.setattr(runtime, "ensure_running", lambda *_a, **_k: pytest.fail("pause must not start a backend"))

    result = runtime.unload_configured_models(timeout_seconds=0.5)

    assert result == {
        "success": True, "backend_available": True,
        "unloaded": ["configured-fast", "configured-subagent"], "failed": {},
    }
    unload_requests = [(payload, timeout) for endpoint, payload, timeout in requests if endpoint == "/api/generate"]
    assert all(payload == {"model": model, "prompt": "", "keep_alive": 0}
               for (payload, _timeout), model in zip(unload_requests, result["unloaded"]))
    assert all(0 < timeout <= 0.5 for _payload, timeout in unload_requests)


def test_pause_requires_explicit_backend_unload_confirmation(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)

    def request(endpoint, payload=None, timeout=None):
        if endpoint == "/api/ps":
            return {"models": [{"name": "configured-fast"}]}
        return {"done": True, "done_reason": "stop"}

    monkeypatch.setattr(runtime, "request", request)

    result = runtime.unload_configured_models(timeout_seconds=0.5)

    assert result == {
        "success": False, "backend_available": True, "unloaded": [],
        "failed": {"configured-fast": "unload failed or timed out"},
    }


def test_pause_is_noop_when_no_configured_models_are_loaded(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    calls = []

    monkeypatch.setattr(runtime, "request", lambda endpoint, payload=None, timeout=None: calls.append(endpoint) or {"models": []})

    result = runtime.unload_configured_models(timeout_seconds=0.5)

    assert result == {"success": True, "backend_available": True, "unloaded": [], "failed": {}}
    assert calls == ["/api/ps"]


def test_pause_reports_backend_unavailable_without_autostart(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(runtime, "request", lambda *_a, **_k: {"error": "offline"})
    monkeypatch.setattr(runtime, "ensure_running", lambda *_a, **_k: pytest.fail("pause must not start a backend"))

    result = runtime.unload_configured_models(timeout_seconds=0.5)

    assert result == {
        "success": False, "backend_available": False, "unloaded": [],
        "failed": {"backend": "backend unavailable"},
    }


def test_pause_reports_loaded_model_when_shared_deadline_expires(tmp_path, monkeypatch):
    import local_ai_hub.ollama as ollama

    runtime = _runtime(tmp_path)
    clock = {"now": 0.0}
    endpoints = []

    def request(endpoint, payload=None, timeout=None):
        endpoints.append(endpoint)
        if endpoint == "/api/ps":
            clock["now"] = 0.06
            return {"models": [{"name": "configured-fast"}]}
        pytest.fail("expired deadline must prevent unload dispatch")

    monkeypatch.setattr(ollama.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(runtime, "request", request)

    result = runtime.unload_configured_models(timeout_seconds=0.05)

    assert result == {
        "success": False, "backend_available": True, "unloaded": [],
        "failed": {"configured-fast": "unload deadline exceeded"},
    }
    assert endpoints == ["/api/ps"]


def test_pause_rejects_invalid_timeout(tmp_path):
    runtime = _runtime(tmp_path)
    with pytest.raises(ValueError, match="finite positive"):
        runtime.unload_configured_models(timeout_seconds=float("inf"))


def test_pause_unloads_configured_llama_cpp_model_with_bounded_timeout(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, ollama_enabled=False)
    timeout_calls = []

    monkeypatch.setattr(runtime.llama_cpp, "_entry", lambda _model: ({"served_model": "served-fast"}, "http://adapter"))
    monkeypatch.setattr(runtime.llama_cpp, "_healthy", lambda _url, timeout: timeout_calls.append(timeout) or True)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"success": True}).encode()

    requests = []

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data) if request.data else None
        requests.append((request.full_url, payload, timeout))
        response = Response()
        response.read = lambda: json.dumps(
            {"data": [{"id": "served-fast", "status": {"value": "loaded"}}]}
            if request.full_url.endswith("/models") else {"success": True}
        ).encode()
        return response

    monkeypatch.setattr("local_ai_hub.ollama.urlopen", fake_urlopen)

    result = runtime.unload_configured_models(timeout_seconds=0.5)

    assert result == {
        "success": True, "backend_available": True,
        "unloaded": ["adapter-fast"], "failed": {},
    }
    unload_request = next(row for row in requests if row[0].endswith("/models/unload"))
    assert unload_request[0] == "http://adapter/models/unload"
    assert unload_request[1] == {"model": "served-fast"}
    assert 0 < unload_request[2] <= 0.5
    assert timeout_calls and 0 < timeout_calls[0] <= 0.5
