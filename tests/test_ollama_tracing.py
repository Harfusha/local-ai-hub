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
    return OllamaRuntime({"server": {"state_dir": str(tmp_path), "ollama_url": "http://ollama", "request_timeout_seconds": 5}})


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

