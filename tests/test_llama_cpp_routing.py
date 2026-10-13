from __future__ import annotations

import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.hardware import profile_overrides
from local_ai_hub.llama_cpp import LlamaCppRouter, _loopback_url, _open_interruptible_response
from local_ai_hub.ollama import OllamaRuntime


class _Response:
    status = 200

    def __init__(self, value: dict | None = None, lines: list[bytes] | None = None, sock=None):
        self.value = value or {}
        self.lines = lines or []
        self.fp = SimpleNamespace(raw=SimpleNamespace(_sock=sock)) if sock is not None else None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.value).encode("utf-8")

    def __iter__(self):
        return iter(self.lines)


class _RecordingSocket:
    def __init__(self):
        self.timeouts: list[float] = []

    def settimeout(self, timeout: float):
        self.timeouts.append(timeout)


class _BlockingSocket(_RecordingSocket):
    def __init__(self):
        super().__init__()
        self.closed = threading.Event()

    def shutdown(self, _how):
        self.closed.set()

    def close(self):
        self.closed.set()


class _BlockingResponse:
    status = 200

    def __init__(self, sock: _BlockingSocket):
        self.fp = SimpleNamespace(raw=SimpleNamespace(_sock=sock))
        self.read_started = threading.Event()
        self.exited = False
        self.sock = sock

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.exited = True
        return False

    def __iter__(self):
        return self

    def __next__(self):
        self.read_started.set()
        if self.sock.closed.wait(1):
            raise OSError("test response socket closed")
        raise TimeoutError("test read should have been cancelled")


@contextmanager
def _connected_socket(*_args, **_kwargs):
    yield None


class LlamaCppRoutingTests(unittest.TestCase):
    def _config(self, vendor: str = "intel", mode: str = "auto") -> dict:
        return {
            "server": {"request_timeout_seconds": 10},
            "_hardware": {"gpus": [{"vendor": vendor, "name": f"{vendor} GPU", "integrated": True}]},
            "llama_cpp": {
                "mode": mode,
                "models": {
                    "qwen2.5-coder:0.5b": {"url": "http://127.0.0.1:12438", "served_model": "hub-qwen-05", "context_length": 16384},
                    "qwen2.5-coder:1.5b": {"url": "http://127.0.0.1:12438", "served_model": "hub-qwen-15", "context_length": 32768},
                    "qwen2.5-coder:3b": {"url": "http://127.0.0.1:12438", "served_model": "hub-qwen-3", "context_length": 32768},
                    "qwen2.5-coder:7b": {"url": "http://127.0.0.1:12438", "served_model": "hub-qwen-7", "context_length": 32768},
                },
            },
        }

    def test_openai_payload_maps_raw_schema_and_preserves_valid_response_formats(self):
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "summary": {"type": "string"},
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "source": {"type": "string"},
                            "element_id": {"type": "string"},
                            "observation_facts": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "field": {"type": "string"},
                                        "value": {"type": "string"},
                                    },
                                    "required": ["field", "value"],
                                },
                            },
                        },
                        "required": ["source", "element_id", "observation_facts"],
                    },
                },
                "recommended_checks": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["summary", "findings", "recommended_checks"],
        }
        openai_schema = {
            "type": "json_schema",
            "json_schema": {"name": "vision-result", "strict": True, "schema": schema},
        }
        llama_schema = {"type": "json_schema", "schema": schema}
        json_object_schema = {"type": "json_object", "schema": schema}
        cases = (
            (schema, llama_schema),
            ("json", {"type": "json_object"}),
            (llama_schema, llama_schema),
            (openai_schema, openai_schema),
            (json_object_schema, json_object_schema),
        )

        for endpoint in ("/api/generate", "/api/chat"):
            for format_value, expected in cases:
                with self.subTest(endpoint=endpoint, format=format_value):
                    payload = {
                        "model": "qwen2.5-coder:3b",
                        "prompt": "Return a summary",
                        "format": format_value,
                    }
                    request = LlamaCppRouter._openai_payload(
                        endpoint, payload, {"served_model": "hub-qwen-3"}
                    )
                    self.assertEqual(request["response_format"], expected)

    def test_auto_uses_only_configured_external_loopback_endpoint_on_any_hardware(self):
        self.assertTrue(LlamaCppRouter(self._config("intel"))._hardware_allows())
        self.assertTrue(LlamaCppRouter(self._config("amd"))._hardware_allows())
        self.assertTrue(LlamaCppRouter(self._config("nvidia"))._hardware_allows())
        self.assertTrue(LlamaCppRouter(self._config("nvidia", "on"))._hardware_allows())

    def test_off_disables_route_even_when_loopback_endpoint_is_configured(self):
        config = self._config()
        config["llama_cpp"]["mode"] = "off"
        self.assertFalse(LlamaCppRouter(config)._hardware_allows())

    def test_unload_model_uses_interruptible_transport_when_controls_are_supplied(self):
        router = LlamaCppRouter(self._config())
        deadline = time.monotonic() + 2.0
        stop = lambda: False

        class _Body:
            status = 200

            def __init__(self) -> None:
                self.body = b'{"success":true}'

            def read(self, _size: int | None = None) -> bytes:
                body, self.body = self.body, b""
                return body

        @contextmanager
        def open_response(request, request_deadline, should_stop):
            self.assertEqual(request.full_url, "http://127.0.0.1:12438/models/unload")
            self.assertEqual(request_deadline, deadline)
            self.assertIs(should_stop, stop)
            yield _Body()

        with patch("local_ai_hub.llama_cpp._open_interruptible_response", open_response):
            self.assertTrue(router.unload_model("qwen2.5-coder:0.5b", should_stop=stop, deadline=deadline))

    def test_ready_for_model_passes_controls_to_probes(self):
        router = LlamaCppRouter(self._config())
        stop = lambda: False
        deadline = time.monotonic() + 2.0
        with patch.object(router, "_healthy", return_value=True) as healthy, patch.object(
            router, "_model_info", return_value={"hub-qwen-05": {}}
        ) as model_info:
            self.assertTrue(router.ready_for_model("qwen2.5-coder:0.5b", should_stop=stop, deadline=deadline))
        self.assertIs(healthy.call_args.kwargs["should_stop"], stop)
        self.assertEqual(healthy.call_args.kwargs["deadline"], deadline)
        self.assertIs(model_info.call_args.kwargs["should_stop"], stop)
        self.assertEqual(model_info.call_args.kwargs["deadline"], deadline)

    def test_disabled_ollama_never_becomes_implicit_provider_fallback(self):
        config = self._config(mode="auto")
        with tempfile.TemporaryDirectory() as state_dir:
            config["server"].update({"ollama_url": "http://127.0.0.1:11434", "state_dir": state_dir})
            config["ollama"] = {"enabled": False}
            config["llama_cpp"]["fallback_to_ollama"] = True
            runtime = OllamaRuntime(config)
            with patch.object(runtime.llama_cpp, "request_stream", return_value={"_lah_backend_unavailable": "endpoint offline"}), \
                 patch("local_ai_hub.ollama._open_interruptible_response", side_effect=AssertionError("disabled Ollama must not be called")):
                result = runtime.request_stream("/api/generate", {"model": "qwen2.5-coder:1.5b"}, lambda _chunk: None, timeout=1)
        self.assertIn("llama.cpp unavailable", result["error"])
        self.assertEqual(result["_lah_provider"], "llama.cpp")

    def test_enabled_ollama_takes_priority_over_llama_cpp_mode(self):
        config = self._config(mode="on")
        with tempfile.TemporaryDirectory() as state_dir:
            config["server"].update({"ollama_url": "http://127.0.0.1:11434", "state_dir": state_dir})
            config["ollama"] = {"enabled": True}
            runtime = OllamaRuntime(config)
            with patch.object(runtime.llama_cpp, "request_stream", side_effect=AssertionError("Ollama is selected")):
                with patch("local_ai_hub.ollama._open_interruptible_response", return_value=_Response(lines=[b'{"response":"ok","done":true}\n'])):
                    result = runtime.request_stream("/api/generate", {"model": "qwen2.5-coder:1.5b", "prompt": "hi"}, lambda _chunk: None, timeout=1)
        self.assertEqual(result.get("response"), "ok")

    def test_router_mode_stream_translates_generate_and_chat(self):
        router = LlamaCppRouter(self._config())
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "summary": {"type": "string"},
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "source": {"type": "string"},
                            "element_id": {"type": "string"},
                        },
                        "required": ["source", "element_id"],
                    },
                },
            },
            "required": ["summary", "findings"],
        }
        lines = [
            b'data: {"choices":[{"delta":{"content":"PASS-27"},"finish_reason":null}]}\n',
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":12,"completion_tokens":1}}\n',
            b"data: [DONE]\n",
        ]

        def fake_urlopen(req, timeout=0):
            if req.full_url.endswith("/health"):
                return _Response({"status": "ok"})
            if req.full_url.endswith("/models"):
                rows = [{"id": entry["served_model"], "status": {"value": "loaded"}} for entry in self._config()["llama_cpp"]["models"].values()]
                return _Response({"data": rows})
            if req.full_url.endswith("/" + "v1" + "/chat/completions"):
                body = json.loads(req.data.decode("utf-8"))
                self.assertEqual(body["model"], "hub-qwen-3")
                self.assertEqual(body["messages"][-1]["content"], "reply only PASS-27")
                self.assertEqual(
                    body["response_format"], {"type": "json_schema", "schema": schema}
                )
                return _Response(lines=lines)
            self.fail(f"unexpected URL: {req.full_url}")

        chunks: list[str] = []
        with patch("local_ai_hub.llama_cpp.socket.create_connection", side_effect=_connected_socket), patch("local_ai_hub.llama_cpp._open_interruptible_response", side_effect=lambda req, deadline, stop: fake_urlopen(req, deadline - time.monotonic())):
            result = router.request_stream(
                "/api/generate",
                {
                    "model": "qwen2.5-coder:3b",
                    "system": "be exact",
                    "prompt": "reply only PASS-27",
                    "options": {"num_predict": 8, "temperature": 0},
                    "format": schema,
                },
                chunks.append,
                timeout=2,
            )
        self.assertEqual(result["response"], "PASS-27")
        self.assertEqual(result["prompt_eval_count"], 12)
        self.assertEqual(chunks, ["PASS-27"])
        self.assertEqual(result["_lah_provider"], "llama.cpp-sycl")

    def test_model_readiness_consumes_request_deadline(self):
        router = LlamaCppRouter(self._config())
        lines = [b'data: {"choices":[{"delta":{"content":"too late"}}]}\n']
        clock = Mock(wraps=time)
        clock.monotonic.side_effect = [100.0, 100.0, 101.0]
        with patch.object(router, "ensure_model", return_value=True) as ensure_model, \
             patch("local_ai_hub.llama_cpp.time", clock), \
             patch("local_ai_hub.llama_cpp._open_interruptible_response", return_value=_Response(lines=lines)) as open_request:
            result = router.request_stream(
                "/api/generate", {"model": "qwen2.5-coder:3b", "prompt": "hi"}, lambda _text: None, timeout=1,
            )

        self.assertTrue(result.get("timed_out"))
        self.assertEqual(ensure_model.call_args.kwargs["deadline"], 101.0)
        open_request.assert_not_called()

    def test_caller_absolute_deadline_is_preserved_for_model_readiness(self):
        router = LlamaCppRouter(self._config())
        shared_monotonic = time.monotonic
        clock = Mock(wraps=time)
        clock.monotonic.side_effect = [100.0, 100.0, 100.1, 100.2]
        with patch.object(router, "ensure_model", return_value=False) as ensure_model, \
             patch("local_ai_hub.llama_cpp.time", clock):
            # Other Hub workers must retain their real shared deadline clock.
            self.assertIs(time.monotonic, shared_monotonic)
            result = router.request_stream(
                "/api/generate", {"model": "qwen2.5-coder:3b", "prompt": "hi"}, lambda _text: None,
                timeout=10, deadline=100.5,
            )

        self.assertIn("_lah_backend_unavailable", result)
        self.assertEqual(ensure_model.call_args.kwargs["deadline"], 100.5)

    def test_model_load_cancellation_is_reported_as_preemption(self):
        router = LlamaCppRouter(self._config())
        cancelled = threading.Event()

        def cancel_during_load(*_args, **_kwargs):
            cancelled.set()
            return False

        with patch.object(router, "ensure_model", side_effect=cancel_during_load) as ensure_model, \
             patch("local_ai_hub.llama_cpp._open_interruptible_response") as open_request:
            result = router.request_stream(
                "/api/generate", {"model": "qwen2.5-coder:3b", "prompt": "hi"}, lambda _text: None,
                timeout=1, should_stop=cancelled.is_set,
            )

        self.assertTrue(result.get("preempted"))
        self.assertFalse(result.get("_lah_backend_unavailable"))
        ensure_model.assert_called_once()
        open_request.assert_not_called()

    def test_health_timeout_and_cancellation_are_not_cached(self):
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled):
                router = LlamaCppRouter(self._config())
                stop = threading.Event()
                calls = 0

                def fake_urlopen(_req, timeout=0):
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        if cancelled:
                            stop.set()
                        else:
                            time.sleep(0.12)
                    return _Response({"status": "ok"})

                with patch("local_ai_hub.llama_cpp.socket.create_connection", side_effect=_connected_socket), patch("local_ai_hub.llama_cpp._open_interruptible_response", side_effect=lambda req, deadline, _stop: fake_urlopen(req, deadline - time.monotonic())):
                    if cancelled:
                        self.assertFalse(router._healthy("http://127.0.0.1:12438", 0.5, should_stop=stop.is_set))
                    else:
                        self.assertFalse(router._healthy("http://127.0.0.1:12438", 0.08))
                    self.assertTrue(router._healthy("http://127.0.0.1:12438", 0.5))

                self.assertEqual(calls, 2)

    def test_model_list_timeout_and_cancellation_are_not_cached(self):
        expected = {"hub-qwen-3": {"id": "hub-qwen-3"}}
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled):
                router = LlamaCppRouter(self._config())
                stop = threading.Event()
                calls = 0

                def fake_urlopen(_req, timeout=0):
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        if cancelled:
                            stop.set()
                        else:
                            time.sleep(0.12)
                    return _Response({"data": [{"id": "hub-qwen-3"}]})

                with patch("local_ai_hub.llama_cpp._open_interruptible_response", side_effect=lambda req, deadline, _stop: fake_urlopen(req, deadline - time.monotonic())):
                    if cancelled:
                        self.assertEqual(router._model_info("http://127.0.0.1:12438", 0.5, should_stop=stop.is_set), {})
                    else:
                        self.assertEqual(router._model_info("http://127.0.0.1:12438", 0.08), {})
                    self.assertEqual(router._model_info("http://127.0.0.1:12438", 0.5), expected)

                self.assertEqual(calls, 2)

    def test_ollama_stream_read_timeout_tracks_remaining_deadline(self):
        config = self._config()
        with tempfile.TemporaryDirectory() as state_dir:
            config["server"].update({"ollama_url": "http://127.0.0.1:11434", "state_dir": state_dir})
            config["ollama"] = {"enabled": True, "request_attempts": 1}
            runtime = OllamaRuntime(config)
            sock = _RecordingSocket()
            response = _Response(lines=[b'{"response":"ok"}\n', b'{"done":true}\n'], sock=sock)
            with patch("local_ai_hub.ollama.time.monotonic", side_effect=[100.0 + step * 0.01 for step in range(50)]), \
                 patch("local_ai_hub.ollama._open_interruptible_response", return_value=response):
                result = runtime.request_stream(
                    "/api/generate", {"model": "qwen2.5-coder:1.5b", "prompt": "hi"}, lambda _text: None, timeout=1,
                )

        self.assertEqual(result.get("response"), "ok")
        self.assertEqual(len(sock.timeouts), 2)
        self.assertTrue(all(timeout > 0.2 for timeout in sock.timeouts))
        self.assertGreater(sock.timeouts[0], sock.timeouts[1])

    def test_llama_stream_deadline_closes_response_and_is_timeout(self):
        router = LlamaCppRouter(self._config())
        sock = _BlockingSocket()
        response = _BlockingResponse(sock)
        deadline = time.monotonic() + 0.15
        with patch.object(router, "ensure_model", return_value=True), \
             patch("local_ai_hub.llama_cpp._open_interruptible_response", return_value=response):
            result = router.request_stream(
                "/api/generate", {"model": "qwen2.5-coder:3b", "prompt": "hi"}, lambda _text: None,
                timeout=2, deadline=deadline,
            )

        self.assertTrue(sock.closed.is_set())
        self.assertTrue(response.exited)
        self.assertTrue(result.get("timed_out"))
        self.assertFalse(result.get("preempted"))

    def test_ollama_forwards_absolute_deadline_and_cancellation_to_llama(self):
        config = self._config()
        with tempfile.TemporaryDirectory() as state_dir:
            config["server"].update({"ollama_url": "http://127.0.0.1:11434", "state_dir": state_dir})
            config["ollama"] = {"enabled": False}
            runtime = OllamaRuntime(config)
            stop = threading.Event()
            should_stop = stop.is_set
            with patch("local_ai_hub.ollama.time.monotonic", side_effect=[100.0, 100.1]), \
                 patch.object(runtime.llama_cpp, "request_stream", return_value={"success": False, "preempted": True}) as stream:
                result = runtime.request_stream(
                    "/api/generate", {"model": "qwen2.5-coder:1.5b", "prompt": "hi"}, lambda _text: None,
                    timeout=10, deadline=100.5, should_stop=should_stop,
                )

        self.assertTrue(result.get("preempted"))
        self.assertEqual(stream.call_args.kwargs["deadline"], 100.5)
        self.assertIs(stream.call_args.kwargs["should_stop"], should_stop)

    def test_ollama_stream_cancellation_closes_blocked_response(self):
        config = self._config()
        with tempfile.TemporaryDirectory() as state_dir:
            config["server"].update({"ollama_url": "http://127.0.0.1:11434", "state_dir": state_dir})
            config["ollama"] = {"enabled": True, "request_attempts": 1}
            runtime = OllamaRuntime(config)
            sock = _BlockingSocket()
            response = _BlockingResponse(sock)
            cancelled = threading.Event()
            result: list[dict] = []
            with patch("local_ai_hub.ollama._open_interruptible_response", return_value=response):
                worker = threading.Thread(target=lambda: result.append(runtime.request_stream(
                    "/api/generate", {"model": "qwen2.5-coder:1.5b", "prompt": "hi"}, lambda _text: None,
                    timeout=2, should_stop=cancelled.is_set,
                )))
                worker.start()
                self.assertTrue(response.read_started.wait(1))
                cancelled.set()
                worker.join(1)

        self.assertFalse(worker.is_alive())
        self.assertTrue(sock.closed.is_set())
        self.assertTrue(response.exited)
        self.assertTrue(result[0].get("preempted"))

    def test_ollama_stream_deadline_closes_response_and_is_timeout(self):
        config = self._config()
        with tempfile.TemporaryDirectory() as state_dir:
            config["server"].update({"ollama_url": "http://127.0.0.1:11434", "state_dir": state_dir})
            config["ollama"] = {"enabled": True, "request_attempts": 1}
            runtime = OllamaRuntime(config)
            sock = _BlockingSocket()
            response = _BlockingResponse(sock)
            deadline = time.monotonic() + 0.15
            with patch("local_ai_hub.ollama._open_interruptible_response", return_value=response):
                result = runtime.request_stream(
                    "/api/generate", {"model": "qwen2.5-coder:1.5b", "prompt": "hi"}, lambda _text: None,
                    timeout=2, deadline=deadline,
                )

        self.assertTrue(sock.closed.is_set())
        self.assertTrue(response.exited)
        self.assertTrue(result.get("timed_out"))
        self.assertFalse(result.get("preempted"))

    def test_llama_stream_cancellation_closes_blocked_response(self):
        router = LlamaCppRouter(self._config())
        sock = _BlockingSocket()
        response = _BlockingResponse(sock)
        cancelled = threading.Event()
        result: list[dict] = []
        with patch.object(router, "ensure_model", return_value=True), \
             patch("local_ai_hub.llama_cpp._open_interruptible_response", return_value=response):
            worker = threading.Thread(target=lambda: result.append(router.request_stream(
                "/api/generate", {"model": "qwen2.5-coder:3b", "prompt": "hi"}, lambda _text: None,
                timeout=2, should_stop=cancelled.is_set,
            )))
            worker.start()
            self.assertTrue(response.read_started.wait(1))
            cancelled.set()
            worker.join(1)

        self.assertFalse(worker.is_alive())
        self.assertTrue(sock.closed.is_set())
        self.assertTrue(response.exited)
        self.assertTrue(result[0].get("preempted"))

    def test_interruptible_response_cancels_before_headers(self):
        request_seen = threading.Event()
        release_handler = threading.Event()

        class _DelayedHeadersHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                request_seen.set()
                release_handler.wait(timeout=3)
                try:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"ok")
                except OSError:
                    pass

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), _DelayedHeadersHandler)
        server.daemon_threads = True
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        cancelled = threading.Event()
        result: list[str] = []
        request = Request(f"http://127.0.0.1:{server.server_port}/slow", data=b"{}")

        def call() -> None:
            try:
                with _open_interruptible_response(request, time.monotonic() + 5, cancelled.is_set):
                    result.append("response")
            except InterruptedError:
                result.append("cancelled")

        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        try:
            self.assertTrue(request_seen.wait(1))
            cancelled.set()
            worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(result, ["cancelled"])
        finally:
            release_handler.set()
            server.shutdown()
            server.server_close()
            server_thread.join(1)
            worker.join(1)

    def test_interruptible_response_enforces_absolute_header_deadline(self):
        request_seen = threading.Event()
        release_handler = threading.Event()

        class _DelayedHeadersHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                request_seen.set()
                release_handler.wait(timeout=2)
                try:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"late")
                except OSError:
                    pass

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), _DelayedHeadersHandler)
        server.daemon_threads = True
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        result: list[str] = []
        request = Request(f"http://127.0.0.1:{server.server_port}/slow")

        def call() -> None:
            try:
                with _open_interruptible_response(request, time.monotonic() + 0.15, None):
                    result.append("response")
            except TimeoutError:
                result.append("timeout")

        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        try:
            self.assertTrue(request_seen.wait(1))
            worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(result, ["timeout"])
        finally:
            release_handler.set()
            server.shutdown()
            server.server_close()
            server_thread.join(1)
            worker.join(1)

    def test_interruptible_response_follows_redirect_and_caps_error_body(self):
        class _RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/ok")
                    self.end_headers()
                    return
                if self.path == "/large-error":
                    body = b"x" * 100_000
                    self.send_response(500)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                body = b"ok"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), _RedirectHandler)
        server.daemon_threads = True
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with _open_interruptible_response(Request(f"{base}/redirect"), time.monotonic() + 2, None) as response:
                self.assertEqual(response.read(), b"ok")
            with self.assertRaises(HTTPError) as raised:
                with _open_interruptible_response(Request(f"{base}/large-error"), time.monotonic() + 2, None):
                    self.fail("HTTP error must preserve urllib behavior")
            self.assertEqual(len(raised.exception.read()), 65_536)
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(1)

    def test_interruptible_response_cancels_during_socket_connect(self):
        connect_started = threading.Event()
        socket_closed = threading.Event()

        class _BlockingConnectSocket:
            def settimeout(self, _timeout):
                pass

            def connect(self, _address):
                connect_started.set()
                if not socket_closed.wait(timeout=2):
                    raise TimeoutError("connect test exceeded deadline")
                raise OSError("socket closed by cancellation")

            def shutdown(self, _how):
                socket_closed.set()

            def close(self):
                socket_closed.set()

        client_socket = _BlockingConnectSocket()
        cancelled = threading.Event()
        result: list[str] = []
        request = Request("http://127.0.0.1:12345/slow")

        def call() -> None:
            try:
                with _open_interruptible_response(request, time.monotonic() + 5, cancelled.is_set):
                    result.append("response")
            except InterruptedError:
                result.append("cancelled")

        worker = threading.Thread(target=call, daemon=True)
        with patch("local_ai_hub.llama_cpp.socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 12345))]), \
             patch("local_ai_hub.llama_cpp.socket.socket", return_value=client_socket):
            worker.start()
            try:
                self.assertTrue(connect_started.wait(1))
                cancelled.set()
                worker.join(1)
                self.assertFalse(worker.is_alive())
                self.assertEqual(result, ["cancelled"])
                self.assertTrue(socket_closed.is_set())
            finally:
                cancelled.set()
                worker.join(1)

    def test_interruptible_response_cancels_during_dns_resolution(self):
        resolver_started = threading.Event()
        release_resolver = threading.Event()
        cancelled = threading.Event()
        result: list[str] = []

        def blocked_resolver(*_args):
            resolver_started.set()
            release_resolver.wait(timeout=2)
            return []

        def call() -> None:
            try:
                with _open_interruptible_response(
                    Request("http://slow-resolver.invalid/"),
                    time.monotonic() + 5,
                    cancelled.is_set,
                ):
                    result.append("response")
            except InterruptedError:
                result.append("cancelled")

        worker = threading.Thread(target=call, daemon=True)
        with patch("local_ai_hub.llama_cpp.socket.getaddrinfo", side_effect=blocked_resolver):
            worker.start()
            try:
                self.assertTrue(resolver_started.wait(1))
                cancelled.set()
                worker.join(0.5)
                self.assertFalse(worker.is_alive(), "DNS resolution held the cancelled request")
                self.assertEqual(result, ["cancelled"])
            finally:
                cancelled.set()
                release_resolver.set()
                worker.join(1)

    def test_interruptible_response_honors_configured_http_proxy(self):
        observed_targets: list[str] = []

        class _ProxyHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                observed_targets.append(self.path)
                body = b"proxied"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), _ProxyHandler)
        server.daemon_threads = True
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        proxy = f"http://127.0.0.1:{server.server_port}"
        request = Request("http://target.invalid/path?q=1")
        fake_addresses = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", server.server_port))
        ]
        try:
            with patch.dict(
                "os.environ",
                {"http_proxy": proxy, "HTTP_PROXY": proxy, "no_proxy": "", "NO_PROXY": ""},
            ), patch("local_ai_hub.llama_cpp.socket.getaddrinfo", return_value=fake_addresses):
                with _open_interruptible_response(request, time.monotonic() + 2, None) as response:
                    self.assertEqual(response.read(), b"proxied")
            self.assertEqual(observed_targets, ["http://target.invalid/path?q=1"])
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(1)

    def test_preprocessing_model_uses_stable_half_billion_alias(self):
        router = LlamaCppRouter(self._config())
        lines = [
            b'data: {"choices":[{"delta":{"content":"PREPROCESS-OK"},"finish_reason":null}]}\n',
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n',
            b"data: [DONE]\n",
        ]

        def fake_urlopen(req, timeout=0):
            if req.full_url.endswith("/health"):
                return _Response({"status": "ok"})
            if req.full_url.endswith("/models"):
                rows = [{"id": entry["served_model"], "status": {"value": "loaded"}} for entry in self._config()["llama_cpp"]["models"].values()]
                return _Response({"data": rows})
            if req.full_url.endswith("/" + "v1" + "/chat/completions"):
                body = json.loads(req.data.decode("utf-8"))
                self.assertEqual(body["model"], "hub-qwen-05")
                return _Response(lines=lines)
            self.fail(f"unexpected URL: {req.full_url}")

        with patch("local_ai_hub.llama_cpp.socket.create_connection", side_effect=_connected_socket), patch("local_ai_hub.llama_cpp._open_interruptible_response", side_effect=lambda req, deadline, _stop: fake_urlopen(req, deadline - time.monotonic())):
            result = router.request_stream(
                "/api/generate",
                {"model": "qwen2.5-coder:0.5b", "prompt": "brief factual card", "options": {"num_predict": 8}},
                lambda _text: None,
                timeout=2,
            )
        self.assertEqual(result["response"], "PREPROCESS-OK")
        self.assertEqual(result["_lah_provider"], "llama.cpp-sycl")

    def test_router_tool_call_arguments_are_returned_in_ollama_shape(self):
        router = LlamaCppRouter(self._config())
        lines = [
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"local_ai_repo","arguments":"{\\\"action\\\":\\\"search\\\"}"}}]},"finish_reason":null}]}\n',
            b'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n',
            b"data: [DONE]\n",
        ]

        def fake_urlopen(req, timeout=0):
            if req.full_url.endswith("/health"):
                return _Response({"status": "ok"})
            if req.full_url.endswith("/models"):
                return _Response({"data": [{"id": "hub-qwen-3", "status": {"value": "loaded"}}]})
            if req.full_url.endswith("/" + "v1" + "/chat/completions"):
                return _Response(lines=lines)
            self.fail(f"unexpected URL: {req.full_url}")

        with patch("local_ai_hub.llama_cpp.socket.create_connection", side_effect=_connected_socket), patch("local_ai_hub.llama_cpp._open_interruptible_response", side_effect=lambda req, deadline, _stop: fake_urlopen(req, deadline - time.monotonic())):
            result = router.request_stream("/api/chat", {"model": "qwen2.5-coder:3b", "messages": []}, lambda _text: None, timeout=2)
        call = result["message"]["tool_calls"][0]
        self.assertEqual(call["id"], "c1")
        self.assertEqual(call["function"]["name"], "local_ai_repo")
        self.assertEqual(call["function"]["arguments"], {"action": "search"})

    def test_model_capabilities_translate_llama_cpp_image_metadata(self):
        config = self._config()
        config["llama_cpp"]["models"]["qwen3-vl:4b"] = {
            "url": "http://127.0.0.1:12438",
            "served_model": "hub-qwen-vl",
            "context_length": 8192,
        }
        router = LlamaCppRouter(config)

        def fake_urlopen(req, timeout=0):
            if req.full_url.endswith("/health"):
                return _Response({"status": "ok"})
            if req.full_url.endswith("/models"):
                return _Response({"data": [{
                    "id": "hub-qwen-vl",
                    "status": {"value": "loaded"},
                    "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
                }]})
            self.fail(f"unexpected URL: {req.full_url}")

        with patch("local_ai_hub.llama_cpp.socket.create_connection", side_effect=_connected_socket), patch("local_ai_hub.llama_cpp._open_interruptible_response", side_effect=lambda req, deadline, _stop: fake_urlopen(req, deadline - time.monotonic())):
            result = router.model_capabilities("qwen3-vl:4b")

        self.assertEqual(result["capabilities"], ["completion", "vision"])

    def test_show_endpoint_uses_llama_cpp_capabilities_when_ollama_disabled(self):
        with tempfile.TemporaryDirectory() as state_dir:
            config = {
                "server": {"ollama_url": "http://127.0.0.1:11434", "state_dir": state_dir},
                "ollama": {"enabled": False},
                "llama_cpp": {"fallback_to_ollama": False, "models": {}},
            }
            runtime = OllamaRuntime(config)
            runtime.llama_cpp = unittest.mock.Mock()
            runtime.llama_cpp.model_capabilities.return_value = {
                "model": "qwen3-vl:4b",
                "capabilities": ["completion", "vision"],
            }

            result = runtime.request("/api/show", {"name": "qwen3-vl:4b"})

        self.assertEqual(result["capabilities"], ["completion", "vision"])
        runtime.llama_cpp.model_capabilities.assert_called_once_with("qwen3-vl:4b")

    def test_context_over_limit_falls_back_without_sending_request(self):
        router = LlamaCppRouter(self._config())
        result = router.request_stream(
            "/api/generate",
            {"model": "qwen2.5-coder:3b", "prompt": "x", "options": {"num_ctx": 32769}},
            lambda _text: None,
        )
        self.assertIn("_lah_backend_unavailable", result)

    def test_only_loopback_endpoints_are_accepted(self):
        self.assertEqual(_loopback_url("http://127.0.0.1:12438"), "http://127.0.0.1:12438")
        self.assertEqual(_loopback_url("http://example.com:12438"), "")
        self.assertEqual(_loopback_url("http://localhost:12438/prefix"), "")

    def test_intel_integrated_profile_disables_ollama_vulkan_but_amd_keeps_it(self):
        intel = profile_overrides("integrated", {"gpus": [{"vendor": "intel", "integrated": True}], "ram": {"total_gb": 32}})
        amd = profile_overrides("integrated", {"gpus": [{"vendor": "amd", "integrated": True}], "ram": {"total_gb": 32}})
        self.assertFalse(intel["ollama"]["allow_integrated_gpu"])
        self.assertFalse(intel["ollama"]["enable_vulkan"])
        self.assertTrue(amd["ollama"]["allow_integrated_gpu"])
        self.assertTrue(amd["ollama"]["enable_vulkan"])

    def test_hardware_profiles_select_model_roles(self):
        expected_background = {
            "cpu": "qwen2.5-coder:3b",
            "integrated": "qwen2.5-coder:3b",
            "low": "qwen2.5-coder:3b",
            "balanced": "qwen2.5-coder:3b",
            "high": "qwen2.5-coder:3b",
            "max": "qwen2.5-coder:3b",
        }
        expected_fast = {
            "cpu": "qwen2.5-coder:3b",
            "integrated": "qwen2.5-coder:3b",
            "low": "qwen2.5-coder:3b",
            "balanced": "qwen2.5-coder:3b",
            "high": "qwen2.5-coder:3b",
            "max": "qwen2.5-coder:3b",
        }
        expected_reasoning = {
            "cpu": "qwen3.5:9b",
            "integrated": "qwen3.5:9b",
            "low": "qwen3.5:9b",
            "balanced": "qwen3.5:9b",
            "high": "qwen3.5:9b",
            "max": "qwen3.5:9b",
        }
        expected_heavy = {
            "cpu": "qwen2.5-coder:7b",
            "integrated": "qwen2.5-coder:7b",
            "low": "qwen2.5-coder:7b",
            "balanced": "qwen2.5-coder:7b",
            "high": "qwen2.5-coder:7b",
            "max": "qwen3.5:9b",
        }
        expected_vision = {
            "cpu": "qwen3-vl:4b",
            "integrated": "qwen3-vl:4b",
            "low": "qwen3-vl:4b",
            "balanced": "qwen3.5:9b",
            "high": "qwen3.5:9b",
            "max": "qwen3.5:9b",
        }
        expected_general = {
            "cpu": "qwen2.5-coder:7b",
            "integrated": "qwen2.5-coder:7b",
            "low": "qwen2.5-coder:7b",
            "balanced": "qwen2.5-coder:7b",
            "high": "qwen3.5:9b",
            "max": "qwen3.5:9b",
        }
        for name in ("cpu", "integrated", "low", "balanced", "high", "max"):
            with self.subTest(profile=name):
                profile = profile_overrides(name, {"gpus": [], "ram": {"total_gb": 32}})
                self.assertEqual(profile["models"]["background_code"], expected_background[name])
                self.assertEqual(profile["models"]["fast_code"], expected_fast[name])
                self.assertEqual(profile["models"]["reasoning"], expected_reasoning[name])
                self.assertEqual(profile["models"]["heavy_code"], expected_heavy[name])
                self.assertEqual(profile["models"]["general"], expected_general[name])
                self.assertEqual(profile["models"]["vision"], expected_vision[name])


if __name__ == "__main__":
    unittest.main()
