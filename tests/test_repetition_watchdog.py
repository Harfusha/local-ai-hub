import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.ollama import OllamaRuntime, RepetitionWatchdog


class _Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class _StreamingResponse(_Response):
    def __init__(self, payload):
        super().__init__(payload)
        self.iterated_chunks = 0

    def __iter__(self):
        for content in self.payload:
            self.iterated_chunks += 1
            chunk = {"message": {"content": content}}
            yield json.dumps(chunk).encode("utf-8") + b"\n"


class RepetitionWatchdogTests(unittest.TestCase):
    def test_detects_repeated_single_word_across_stream_chunks(self):
        watchdog = RepetitionWatchdog()

        self.assertFalse(watchdog.push("text "))
        self.assertFalse(watchdog.push("text "))
        self.assertFalse(watchdog.push("text "))
        self.assertTrue(watchdog.push("text "))

    def test_detects_repeated_phrase_across_stream_chunks(self):
        watchdog = RepetitionWatchdog()

        self.assertFalse(watchdog.push("return only facts "))
        self.assertFalse(watchdog.push("return only facts "))
        self.assertTrue(watchdog.push("return only facts"))

    def test_detects_long_repeated_cycle_in_one_delta(self):
        watchdog = RepetitionWatchdog()
        cycle = "amber birch cedar delta elm fir grove hazel iris"
        response = " ".join([cycle] * 3)

        self.assertFalse(watchdog._check_word_loop())
        self.assertTrue(watchdog.push(response))

    def test_does_not_reject_normal_prose_with_a_repeated_word(self):
        watchdog = RepetitionWatchdog()

        self.assertFalse(watchdog.push("No, no, that is useful. "))
        self.assertFalse(watchdog.push("The answer is concise and complete."))

    def test_repeated_model_response_fails_closed(self):
        runtime = object.__new__(OllamaRuntime)
        runtime.llama_cpp = Mock()
        runtime.llama_cpp.request_stream.return_value = None
        runtime.config = {"ollama": {"request_attempts": 1}}
        runtime.base_url = "http://ollama/"
        runtime.timeout = 1.0
        response = _StreamingResponse(["text ", "text ", "text ", "text ", "unused output"])

        with patch("local_ai_hub.ollama.urlopen", return_value=response) as urlopen_mock:
            result = runtime.request("/api/chat", {"model": "test", "messages": [], "stream": False})

        self.assertTrue(json.loads(urlopen_mock.call_args.args[0].data)["stream"])
        self.assertEqual(response.iterated_chunks, 4)
        self.assertTrue(result["_lah_repetition_loop_detected"])
        self.assertIn("repetition loop", result["error"])

    def test_repeated_streamed_response_fails_closed(self):
        runtime = object.__new__(OllamaRuntime)
        runtime.llama_cpp = Mock()
        runtime.llama_cpp.request_stream.return_value = None
        runtime.config = {"ollama": {"request_attempts": 1}}
        runtime.base_url = "http://ollama/"
        runtime.timeout = 1.0
        response = _StreamingResponse(["text ", "text ", "text ", "text "])

        with patch("local_ai_hub.ollama.urlopen", return_value=response):
            result = runtime.request_stream("/api/chat", {"model": "test", "messages": []}, lambda _chunk: None)

        self.assertTrue(result["_lah_repetition_loop_detected"])
        self.assertIn("repetition loop", result["error"])


if __name__ == "__main__":
    unittest.main()
