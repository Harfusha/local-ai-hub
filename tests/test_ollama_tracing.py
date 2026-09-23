from __future__ import annotations

import json

from local_ai_hub.ollama import OllamaRuntime


class _Response:
    def __init__(self, lines):
        self.lines = [line.encode("utf-8") for line in lines]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def __iter__(self):
        return iter(self.lines)


def _runtime(tmp_path):
    return OllamaRuntime({"server": {"state_dir": str(tmp_path), "ollama_url": "http://ollama", "request_timeout_seconds": 5}, "ollama": {"enabled": True}})


def test_request_stream_aggregates_generate_chunks_and_notifies_callback(tmp_path, monkeypatch):
    response = _Response([
        json.dumps({"model": "m", "response": "hel", "done": False}),
        json.dumps({"response": "lo", "done": True, "total_duration": 7}),
    ])
    monkeypatch.setattr("local_ai_hub.ollama.urlopen", lambda *_args, **_kwargs: response)
    chunks = []

    result = _runtime(tmp_path).request_stream("/api/generate", {"model": "m", "prompt": "p"}, chunks.append)

    assert chunks == ["hel", "lo"]
    assert result["response"] == "hello"
    assert result["done"] is True
    assert result["total_duration"] == 7


def test_request_stream_separates_thinking_and_ignores_empty_output_chunks(tmp_path, monkeypatch):
    response = _Response([
        json.dumps({"model": "m", "thinking": "reason ", "response": "", "done": False}),
        json.dumps({"thinking": "more", "response": "final", "done": True}),
    ])
    monkeypatch.setattr("local_ai_hub.ollama.urlopen", lambda *_args, **_kwargs: response)
    chunks = []
    thinking = []

    result = _runtime(tmp_path).request_stream(
        "/api/generate", {"model": "m", "prompt": "p"}, chunks.append, on_thinking=thinking.append
    )

    assert chunks == ["final"]
    assert thinking == ["reason ", "more"]
    assert result["response"] == "final"
    assert result["thinking"] == "reason more"


def test_generate_promotes_benchmark_think_flag_to_ollama_payload(tmp_path):
    runtime = _runtime(tmp_path)
    seen = {}

    def request(endpoint, payload):
        seen["endpoint"] = endpoint
        seen["payload"] = payload
        return {"response": "ok"}

    runtime.request = request
    result = runtime.generate("qwen3.5:9b", "Return ok", options={"num_predict": 8, "think": False})

    assert result["response"] == "ok"
    assert seen["endpoint"] == "/api/generate"
    assert seen["payload"]["think"] is False
    assert seen["payload"]["options"] == {"num_predict": 8}


def test_request_stream_aggregates_chat_content_and_ignores_bad_lines(tmp_path, monkeypatch):
    response = _Response([
        b"not-json".decode(),
        json.dumps({"message": {"role": "assistant", "content": "one"}, "done": False}),
        json.dumps({"message": {"content": " two"}, "done": True}),
    ])
    monkeypatch.setattr("local_ai_hub.ollama.urlopen", lambda *_args, **_kwargs: response)
    chunks = []

    result = _runtime(tmp_path).request_stream("/api/chat", {"model": "m", "messages": []}, chunks.append)

    assert chunks == ["one", " two"]
    assert result["message"]["content"] == "one two"
