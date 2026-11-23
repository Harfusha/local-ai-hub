import io
import json

from local_ai_hub import ollama


def test_stream_preserves_tool_calls_before_final_chunk(monkeypatch):
    tool_call = {"function": {"name": "repo_search", "arguments": {"query": "validate"}}}
    chunks = [
        {"message": {"role": "assistant", "content": "", "tool_calls": [tool_call]}, "done": False},
        {"message": {"role": "assistant", "content": ""}, "done": True},
    ]
    captured = {}

    def open_stream(request, timeout):
        captured.update(json.loads(request.data))
        return io.BytesIO(b"".join(json.dumps(chunk).encode() + b"\n" for chunk in chunks))

    monkeypatch.setattr(ollama, "urlopen", open_stream)
    runtime = object.__new__(ollama.OllamaRuntime)
    runtime.base_url = "http://127.0.0.1:11434"
    runtime.config = {"server": {}, "ollama": {"enabled": True}}
    result = runtime._request_stream_impl(
        "/api/chat", {"model": "test", "tools": [{"type": "function"}]}, None, timeout=5
    )

    assert captured.get("tools") == [{"type": "function"}], result
    assert result["message"]["tool_calls"] == [tool_call]


def test_stream_rejects_malformed_tool_calls(monkeypatch):
    chunk = {"message": {"tool_calls": "not an array"}, "done": True}
    monkeypatch.setattr(ollama, "urlopen", lambda request, timeout: io.BytesIO(json.dumps(chunk).encode() + b"\n"))
    runtime = object.__new__(ollama.OllamaRuntime)
    runtime.base_url = "http://127.0.0.1:11434"
    runtime.config = {"server": {}, "ollama": {"enabled": True}}
    result = runtime._request_stream_impl("/api/chat", {"model": "test"}, None, timeout=5)
    assert result["error"] == "invalid streamed tool_calls"
    assert result["retryable"] is False


def test_stream_on_chunk_and_thinking_exception_logged_not_crashed(monkeypatch, caplog):
    import logging
    chunks = [
        {"message": {"role": "assistant", "content": "hello", "thinking": "reasoning"}, "done": False},
        {"message": {"role": "assistant", "content": " world"}, "done": True},
    ]
    monkeypatch.setattr(
        ollama, "urlopen",
        lambda request, timeout: io.BytesIO(b"".join(json.dumps(chunk).encode() + b"\n" for chunk in chunks))
    )
    runtime = object.__new__(ollama.OllamaRuntime)
    runtime.base_url = "http://127.0.0.1:11434"
    runtime.config = {"server": {}, "ollama": {"enabled": True}}

    def bad_chunk(text):
        raise RuntimeError("chunk failure")

    def bad_thinking(text):
        raise ValueError("thinking failure")

    with caplog.at_level(logging.DEBUG, logger=ollama.logger.name):
        result = runtime._request_stream_impl(
            "/api/chat", {"model": "test"}, bad_chunk, timeout=5, on_thinking=bad_thinking
        )

    assert result["message"]["content"] == "hello world"
    assert "on_chunk callback failed: RuntimeError" in caplog.text
    assert "on_thinking callback failed: ValueError" in caplog.text
