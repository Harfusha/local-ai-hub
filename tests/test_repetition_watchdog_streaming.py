from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from local_ai_hub.ollama import OllamaRuntime, RepetitionWatchdog


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
            chunk = {"message": {"content": content}}
            yield json.dumps(chunk).encode("utf-8") + b"\n"


class RepetitionWatchdogStreamingTests(unittest.TestCase):
    def test_detects_long_repeated_ngram_cycle_in_one_delta(self):
        watchdog = RepetitionWatchdog()
        cycle = "amber birch cedar delta elm fir grove hazel iris"

        self.assertTrue(watchdog.push(" ".join([cycle] * 3)))
        self.assertTrue(watchdog.loop_detected)

    def test_non_streaming_request_rejects_and_stops_repetitive_output(self):
        runtime = object.__new__(OllamaRuntime)
        runtime.config = {"ollama": {"request_attempts": 1}}
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
        self.assertEqual(response.iterated_chunks, 4)
        self.assertTrue(result["_lah_repetition_loop_detected"])
        self.assertIn("repetition loop", result["error"])
        self.assertNotIn("message", result)

    def test_interruptible_request_rejects_repetitive_output(self):
        runtime = object.__new__(OllamaRuntime)
        runtime.config = {"ollama": {"request_attempts": 1}}
        runtime.base_url = "http://ollama/"
        runtime.timeout = 1.0
        response = StreamingResponse(["text ", "text ", "text ", "text ", "unused output"])

        with patch("local_ai_hub.ollama.urlopen", return_value=response):
            result = runtime.request_interruptible(
                "/api/chat",
                {"model": "test", "messages": []},
                lambda: False,
            )

        self.assertTrue(result["_lah_repetition_loop_detected"])
        self.assertIn("repetition loop", result["error"])
        self.assertNotIn("message", result)


if __name__ == "__main__":
    unittest.main()
