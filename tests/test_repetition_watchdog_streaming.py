from __future__ import annotations

import json
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from local_ai_hub.ollama import OllamaRuntime, RepetitionWatchdog
from local_ai_hub.scheduler import AffinityScheduler


class StreamingResponse:
    def __init__(self, chunks: list[str]):
        self.chunks = chunks
        self.iterated_chunks = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def __iter__(self):
        for content in self.chunks:
            self.iterated_chunks += 1
            if isinstance(content, BaseException):
                raise content
            chunk = content if isinstance(content, dict) else {"message": {"content": content}}
            yield json.dumps(chunk).encode("utf-8") + b"\n"


class RepetitionWatchdogStreamingTests(unittest.TestCase):
    def test_detects_long_repeated_ngram_cycle_in_one_delta(self):
        watchdog = RepetitionWatchdog()
        cycle = "amber birch cedar delta elm fir grove hazel iris"

        self.assertTrue(watchdog.push(" ".join([cycle] * 3)))
        self.assertTrue(watchdog.loop_detected)

    def test_non_streaming_request_rejects_and_stops_repetitive_output(self):
        runtime = object.__new__(OllamaRuntime)
        runtime.config = {"ollama": {"enabled": True, "request_attempts": 1}}
        runtime.base_url = "http://ollama/"
        runtime.timeout = 1.0
        response = StreamingResponse(["text ", "text ", "text ", "text ", "unused output"])

        with patch("local_ai_hub.ollama.urlopen", return_value=response) as urlopen_mock:
            result = runtime.request(
                "/api/chat",
                {"model": "test", "messages": [], "stream": False},
            )

        request = urlopen_mock.call_args.args[0]
        self.assertTrue(json.loads(request.data)["stream"])
        self.assertEqual(response.iterated_chunks, len(response.chunks))
        self.assertTrue(result["_lah_repetition_loop_detected"])
        self.assertIsNot(result.get("_lah_backend_completed"), True)
        self.assertIn("repetition loop", result["error"])
        self.assertNotIn("message", result)

    def test_repetition_waits_for_confirmed_backend_end(self):
        runtime = object.__new__(OllamaRuntime)
        runtime.config = {"ollama": {"enabled": True, "request_attempts": 1}}
        runtime.base_url = "http://ollama/"
        runtime.timeout = 1.0
        response = StreamingResponse(["text ", "text ", "text ", "text ", "discarded", {"done": True}])
        with patch("local_ai_hub.ollama.urlopen", return_value=response):
            result = runtime.request("/api/chat", {"model": "test", "messages": []})
        self.assertEqual(response.iterated_chunks, len(response.chunks))
        self.assertTrue(result["_lah_repetition_loop_detected"])
        self.assertIs(result.get("_lah_backend_completed"), True)
        self.assertNotIn("message", result)

    def test_repetition_done_on_detection_chunk_is_confirmed(self):
        runtime = object.__new__(OllamaRuntime)
        runtime.config = {"ollama": {"enabled": True, "request_attempts": 1}}
        runtime.base_url = "http://ollama/"
        runtime.timeout = 1.0
        response = StreamingResponse([{"response": "text "}] * 3 + [{"response": "text ", "done": True}])
        with patch("local_ai_hub.ollama.urlopen", return_value=response):
            result = runtime.request("/api/generate", {"model": "test", "prompt": "x"})
        self.assertTrue(result["_lah_repetition_loop_detected"])
        self.assertIs(result.get("_lah_backend_completed"), True)

    def test_repetition_drain_timeout_is_not_backend_completion(self):
        runtime = object.__new__(OllamaRuntime)
        runtime.config = {"ollama": {"enabled": True, "request_attempts": 1}}
        runtime.base_url = "http://ollama/"
        runtime.timeout = 1.0
        response = StreamingResponse(["text "] * 4 + [socket.timeout("deadline")])
        with patch("local_ai_hub.ollama.urlopen", return_value=response):
            result = runtime.request("/api/chat", {"model": "test", "messages": []})
        self.assertIs(result.get("timed_out"), True)
        self.assertIsNot(result.get("_lah_backend_completed"), True)

    def test_repetition_drain_does_not_publish_later_chunks(self):
        runtime = object.__new__(OllamaRuntime)
        runtime.config = {"ollama": {"enabled": True, "request_attempts": 1}}
        runtime.base_url = "http://ollama/"
        runtime.timeout = 1.0
        response = StreamingResponse(["text "] * 4 + ["discarded", {"done": True}])
        published = []
        with patch("local_ai_hub.ollama.urlopen", return_value=response):
            result = runtime.request_stream("/api/chat", {"model": "test", "messages": []}, published.append)
        self.assertEqual(published, ["text "] * 4)
        self.assertIs(result.get("_lah_backend_completed"), True)

    def test_repetition_drain_backend_error_is_not_completion(self):
        runtime = object.__new__(OllamaRuntime)
        runtime.config = {"ollama": {"enabled": True, "request_attempts": 1}}
        runtime.base_url = "http://ollama/"
        runtime.timeout = 1.0
        response = StreamingResponse(["text "] * 4 + [{"error": "backend failed"}, {"done": True}])
        with patch("local_ai_hub.ollama.urlopen", return_value=response):
            result = runtime.request("/api/chat", {"model": "test", "messages": []})
        self.assertTrue(result["_lah_repetition_loop_detected"])
        self.assertIsNot(result.get("_lah_backend_completed"), True)

    def test_interruptible_request_rejects_repetitive_output(self):
        runtime = object.__new__(OllamaRuntime)
        runtime.config = {"ollama": {"enabled": True, "request_attempts": 1}}
        runtime.base_url = "http://ollama/"
        runtime.timeout = 1.0
        response = StreamingResponse(["text ", "text ", "text ", "text ", "unused output"])

        with patch("local_ai_hub.ollama._open_interruptible_response", return_value=response):
            result = runtime.request_interruptible(
                "/api/chat",
                {"model": "test", "messages": []},
                lambda: False,
            )

        self.assertTrue(result["_lah_repetition_loop_detected"])
        self.assertIn("repetition loop", result["error"])
        self.assertNotIn("message", result)


@pytest.mark.parametrize("ending,uncertain", [({"done": True}, False), (None, True), (socket.timeout("deadline"), True)])
def test_repetition_fence_requires_backend_completion(tmp_path, ending, uncertain):
    backend = object.__new__(OllamaRuntime)
    backend.config = {"ollama": {"enabled": True, "request_attempts": 1}}
    backend.base_url = "http://ollama/"
    backend.timeout = 1.0
    response = StreamingResponse(["text "] * 4 + ([] if ending is None else [ending]))
    scheduler = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), {"server": {"state_dir": str(tmp_path)}})

    def switch(model, **_kwargs):
        with scheduler._cond:
            scheduler._active_model = model
            scheduler._switching = False
            scheduler._cond.notify_all()
        return True

    scheduler._perform_switch = switch
    try:
        with patch("local_ai_hub.ollama.urlopen", return_value=response):
            result = scheduler.submit("model", source="test", execute=lambda: backend.request(
                "/api/chat", {"model": "model", "messages": []}), wait_timeout=3)
        assert bool(result.get("outcome_unknown")) is uncertain
        with scheduler._cond:
            assert scheduler._internal_gpu_uncertain is uncertain
            assert scheduler._release_internal_gpu() is (not uncertain)
    finally:
        scheduler.close()


if __name__ == "__main__":
    unittest.main()
