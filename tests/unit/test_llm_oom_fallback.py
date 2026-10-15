"""Deferred bundle regression source; provider responses are in-memory streams."""
import copy
import json
from io import BytesIO
from types import SimpleNamespace

from local_ai_hub import ollama as module
from local_ai_hub.ollama import OllamaRuntime, _oom_context_request


def _runtime():
    runtime = object.__new__(OllamaRuntime)
    runtime.config = {"ollama": {"enabled": True, "request_attempts": 2, "retry_delay_seconds": 0}}
    runtime.base_url = "http://fake.invalid"
    runtime.timeout = 5
    runtime.llama_cpp = None
    runtime.model_policy = SimpleNamespace(profile=lambda _model: SimpleNamespace(num_ctx=8192))
    return runtime


def _response(chunks):
    return BytesIO(b"".join(json.dumps(chunk).encode() + b"\n" for chunk in chunks))


def test_oom_halves_context_once_without_mutating_input(monkeypatch):
    runtime = _runtime()
    bodies = []
    responses = [_response([{"error": "CUDA out of memory"}]),
                 _response([{"response": "ok", "done": True}])]

    def open_request(request, **_kwargs):
        bodies.append(json.loads(request.data))
        return responses.pop(0)

    monkeypatch.setattr(module, "urlopen", open_request)
    payload = {"model": "fake", "prompt": "small input", "options": {"num_ctx": 8192, "num_predict": 32}}
    original = copy.deepcopy(payload)
    result = runtime.request_stream("/api/generate", payload, None)
    assert result["response"] == "ok"
    assert [body["options"]["num_ctx"] for body in bodies] == [8192, 4096]
    assert payload == original
    assert result["context_recovery"]["input_truncated"] is False
    assert result["_lah_retry_count"] == 1


def test_partial_stream_then_error_is_failure_without_retry(monkeypatch):
    runtime = _runtime()
    calls = []
    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: calls.append(True) or _response([
        {"response": "partial", "done": False}, {"error": "CUDA out of memory"},
    ]))
    result = runtime.request_stream("/api/generate", {"model": "fake", "prompt": "x"}, None)
    assert "error" in result
    assert result["_lah_partial_response"] is True
    assert len(calls) == 1


def test_thinking_callback_then_error_is_not_replayed(monkeypatch):
    runtime = _runtime()
    calls, thinking = [], []
    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: calls.append(True) or _response([
        {"thinking": "partial reasoning"}, {"error": "CUDA out of memory"},
    ]))
    result = runtime.request_stream("/api/generate", {"model": "fake", "prompt": "x"}, None,
                                    on_thinking=thinking.append)
    assert "error" in result
    assert thinking == ["partial reasoning"]
    assert len(calls) == 1


def test_reduced_window_never_silently_discards_input():
    payload = {"model": "fake", "prompt": "x" * 5000, "options": {"num_ctx": 8192}}
    adjusted, metadata = _oom_context_request(payload, 8192)
    assert adjusted is None
    assert metadata["reason"] == "retained_input_exceeds_reduced_budget"
    assert metadata["input_truncated"] is False
