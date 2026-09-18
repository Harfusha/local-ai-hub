"""Optional loopback llama.cpp SYCL adapter for Ollama-shaped Hub calls.

The Hub continues to use Ollama for model management and as a fallback.  This
adapter only translates inference requests for explicitly mapped models when a
local llama.cpp server is healthy and Intel SYCL routing is enabled.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from .json_utils import dumps as json_dumps


def _loopback_url(value: Any) -> str:
    url = str(value or "").strip().rstrip("/")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    host = parsed.hostname.lower()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        return ""
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        return ""
    return url


class LlamaCppRouter:
    """Translate mapped Ollama chat/generate calls to local OpenAI-compatible APIs."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.settings = config.get("llama_cpp", {}) if isinstance(config.get("llama_cpp", {}), dict) else {}
        self._health_lock = threading.Lock()
        self._health: dict[str, tuple[float, bool]] = {}
        self._models: dict[str, tuple[float, dict[str, dict[str, Any]]]] = {}

    def _hardware_allows(self) -> bool:
        mode = str(self.settings.get("mode", "auto")).strip().lower()
        if mode == "off":
            return False
        if mode == "on":
            return True
        if mode != "auto":
            return False
        hardware = self.config.get("_hardware", {})
        hardware = hardware if isinstance(hardware, dict) else {}
        gpus = hardware.get("gpus", [])
        if not isinstance(gpus, list):
            return False
        intel = any(
            str(item.get("vendor", "")).lower() == "intel"
            or "intel" in str(item.get("name", "")).lower()
            for item in gpus if isinstance(item, dict)
        )
        dedicated_other = any(
            str(item.get("vendor", "")).lower() in {"amd", "nvidia"}
            and not bool(item.get("integrated"))
            for item in gpus if isinstance(item, dict)
        )
        return intel and not dedicated_other

    def _entry(self, model: str) -> tuple[dict[str, Any], str] | None:
        if not self._hardware_allows():
            return None
        models = self.settings.get("models", {})
        raw = models.get(str(model or "").strip()) if isinstance(models, dict) else None
        if not isinstance(raw, dict):
            return None
        url = _loopback_url(raw.get("url"))
        if not url:
            return None
        return raw, url

    def supports_model(self, model: str) -> bool:
        models = self.settings.get("models", {})
        return isinstance(models, dict) and isinstance(models.get(str(model or "").strip()), dict)

    def _healthy(self, url: str, timeout: float) -> bool:
        now = time.monotonic()
        with self._health_lock:
            cached = self._health.get(url)
            if cached and now - cached[0] < 1.0:
                return cached[1]
        healthy = False
        try:
            req = Request(f"{url}/health", headers={"Accept": "application/json"})
            with urlopen(req, timeout=min(max(0.05, timeout), 0.6)) as response:
                healthy = 200 <= int(getattr(response, "status", 200)) < 300
        except Exception:
            healthy = False
        with self._health_lock:
            self._health[url] = (time.monotonic(), healthy)
        return healthy

    def _model_info(self, url: str, timeout: float = 0.8) -> dict[str, dict[str, Any]]:
        now = time.monotonic()
        with self._health_lock:
            cached = self._models.get(url)
            if cached and now - cached[0] < 1.0:
                return cached[1]
        result: dict[str, dict[str, Any]] = {}
        try:
            req = Request(f"{url}/models", headers={"Accept": "application/json"})
            with urlopen(req, timeout=min(max(0.05, timeout), 1.0)) as response:
                body = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
            rows = body.get("data", []) if isinstance(body, dict) else []
            if isinstance(rows, list):
                result = {str(row.get("id")): row for row in rows if isinstance(row, dict) and row.get("id")}
        except Exception:
            pass
        with self._health_lock:
            self._models[url] = (time.monotonic(), result)
        return result

    def ready_for_model(self, model: str) -> bool:
        selected = self._entry(model)
        if not selected:
            return False
        entry, url = selected
        if not self._healthy(url, 0.6):
            return False
        alias = str(entry.get("served_model") or model)
        return alias in self._model_info(url)

    def ensure_model(self, model: str, timeout: float | None = None, should_stop: Any | None = None) -> bool:
        selected = self._entry(model)
        if not selected:
            return False
        entry, url = selected
        if not self._healthy(url, 0.6):
            return False
        alias = str(entry.get("served_model") or model)
        models = self._model_info(url)
        if alias not in models:
            return False
        row = models[alias]
        status = row.get("status", {}) if isinstance(row.get("status"), dict) else {}
        state = str(status.get("value", "")).lower()
        if state == "loaded":
            return True
        if state != "loading":
            try:
                body = json_dumps({"model": alias}).encode("utf-8")
                req = Request(f"{url}/models/load", data=body, headers={"Content-Type": "application/json"})
                with urlopen(req, timeout=min(max(0.05, float(timeout or 60.0)), 300.0)) as response:
                    loaded = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
                if isinstance(loaded, dict) and loaded.get("success") is False:
                    return False
            except Exception:
                return False
        deadline = time.monotonic() + min(max(0.1, float(timeout or 60.0)), 300.0)
        while time.monotonic() < deadline:
            if should_stop is not None:
                try:
                    if bool(should_stop()):
                        return False
                except Exception:
                    pass
            self._models.pop(url, None)
            current = self._model_info(url, timeout=0.8).get(alias, {})
            current_status = current.get("status", {}) if isinstance(current.get("status"), dict) else {}
            value = str(current_status.get("value", "")).lower()
            if value == "loaded":
                return True
            if current_status.get("failed"):
                return False
            time.sleep(0.25)
        return False

    def available_models(self) -> list[str]:
        models = self.settings.get("models", {})
        if not isinstance(models, dict) or not self._hardware_allows():
            return []
        available: list[str] = []
        for model, entry in models.items():
            if not isinstance(entry, dict):
                continue
            selected = self._entry(str(model))
            if selected and self._healthy(selected[1], 0.6):
                alias = str(entry.get("served_model") or model)
                if alias in self._model_info(selected[1]):
                    available.append(str(model))
        return available

    def is_online(self) -> bool:
        return bool(self.available_models())

    def loaded_model_details(self) -> list[dict[str, Any]]:
        models = self.settings.get("models", {})
        if not isinstance(models, dict):
            return []
        rows = []
        for model in self.available_models():
            entry = models.get(model, {})
            selected = self._entry(model)
            status = self._model_info(selected[1]).get(str(entry.get("served_model") or model), {}).get("status", {}) if selected else {}
            if isinstance(status, dict) and str(status.get("value", "")).lower() != "loaded":
                continue
            rows.append({
                "name": model,
                "parameter_size": "",
                "quantization": "GGUF",
                "size_bytes": 0,
                "vram_bytes": 0,
                "cpu_bytes": 0,
                "gpu_fraction": 0.0,
                "cpu_offload_fraction": 0.0,
                "context_length": int(entry.get("context_length", 0) or 0) if isinstance(entry, dict) else 0,
                "backend": "llama.cpp-sycl",
            })
        return rows

    def unload_model(self, model: str) -> bool:
        selected = self._entry(model)
        if not selected:
            return False
        entry, url = selected
        alias = str(entry.get("served_model") or model)
        try:
            body = json_dumps({"model": alias}).encode("utf-8")
            req = Request(f"{url}/models/unload", data=body, headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=5.0) as response:
                result = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
            self._models.pop(url, None)
            return bool(isinstance(result, dict) and result.get("success", False))
        except Exception:
            return False

    @staticmethod
    def _messages(endpoint: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if endpoint == "/api/chat":
            messages = payload.get("messages", [])
            if not isinstance(messages, list):
                return []
            converted: list[dict[str, Any]] = []
            for item in messages:
                if not isinstance(item, dict):
                    continue
                message = dict(item)
                if message.get("role") == "tool" and message.get("tool_name") and not message.get("name"):
                    message["name"] = message.pop("tool_name")
                converted.append(message)
            return converted
        messages = []
        system = str(payload.get("system", "") or "")
        prompt = str(payload.get("prompt", "") or "")
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    @staticmethod
    def _openai_payload(endpoint: str, payload: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
        options = payload.get("options", {})
        options = options if isinstance(options, dict) else {}
        result: dict[str, Any] = {
            "model": str(entry.get("served_model") or payload.get("model") or ""),
            "messages": LlamaCppRouter._messages(endpoint, payload),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        for source, target in (
            ("num_predict", "max_tokens"), ("temperature", "temperature"), ("top_p", "top_p"),
            ("top_k", "top_k"), ("seed", "seed"), ("stop", "stop"),
            ("repeat_penalty", "repeat_penalty"),
        ):
            if source in options:
                result[target] = options[source]
        if isinstance(payload.get("tools"), list):
            result["tools"] = payload["tools"]
        fmt = payload.get("format")
        if fmt == "json":
            result["response_format"] = {"type": "json_object"}
        elif isinstance(fmt, dict):
            result["response_format"] = {"type": "json_schema", "json_schema": fmt}
        return result

    @staticmethod
    def _tool_calls(state: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []
        for index in sorted(state):
            item = state[index]
            function = item.get("function", {})
            raw_args = str(function.get("arguments", "") or "")
            try:
                arguments: Any = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                arguments = raw_args
            calls.append({
                "id": str(item.get("id", "")),
                "type": "function",
                "function": {"name": str(function.get("name", "")), "arguments": arguments},
            })
        return calls

    def request_stream(
        self,
        endpoint: str,
        payload: dict[str, Any] | None,
        on_chunk: Any,
        timeout: float | None = None,
        should_stop: Any | None = None,
        on_thinking: Any | None = None,
    ) -> dict[str, Any] | None:
        if endpoint not in {"/api/chat", "/api/generate"} or not isinstance(payload, dict):
            return None
        selected = self._entry(str(payload.get("model", "")))
        if not selected:
            return None
        entry, url = selected
        options = payload.get("options", {})
        try:
            requested_ctx = int(options.get("num_ctx", 0) or 0) if isinstance(options, dict) else 0
        except (TypeError, ValueError):
            requested_ctx = 0
        configured_ctx = int(entry.get("context_length", 0) or 0)
        if requested_ctx and configured_ctx and requested_ctx > configured_ctx:
            return {"_lah_backend_unavailable": f"SYCL server context is {configured_ctx}, request needs {requested_ctx}"}
        total_timeout = max(0.05, float(timeout if timeout is not None else self.config.get("server", {}).get("request_timeout_seconds", 300)))
        if not self.ensure_model(str(payload.get("model", "")), timeout=min(total_timeout, float(self.settings.get("model_load_timeout_seconds", 600))), should_stop=should_stop):
            return {"_lah_backend_unavailable": "local llama.cpp SYCL server is not ready"}
        try:
            from .ollama import RepetitionWatchdog
        except Exception:
            return {"error": "repetition watchdog unavailable"}

        body = json_dumps(self._openai_payload(endpoint, payload, entry)).encode("utf-8")
        req = Request(
            urljoin(f"{url.rstrip('/')}/", "v1/chat/completions"), data=body,
            headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        )
        deadline = time.monotonic() + total_timeout
        watchdog = RepetitionWatchdog(max_repeat=3)
        text_parts: list[str] = []
        tool_state: dict[int, dict[str, Any]] = {}
        prompt_tokens = output_tokens = 0
        finish_reason: str | None = None
        try:
            with urlopen(req, timeout=total_timeout) as response:
                for raw_line in response:
                    if time.monotonic() >= deadline:
                        return {"error": f"llama.cpp request timed out after {total_timeout:g}s", "timed_out": True}
                    if should_stop is not None:
                        try:
                            if bool(should_stop()):
                                return {"success": False, "preempted": True, "error": "background request preempted by foreground work"}
                        except Exception:
                            pass
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(chunk, dict) and chunk.get("error"):
                        return {"error": f"llama.cpp: {chunk['error']}", "_lah_provider": "llama.cpp-sycl"}
                    usage = chunk.get("usage", {}) if isinstance(chunk, dict) else {}
                    if isinstance(usage, dict):
                        prompt_tokens = int(usage.get("prompt_tokens", prompt_tokens) or prompt_tokens)
                        output_tokens = int(usage.get("completion_tokens", output_tokens) or output_tokens)
                    choices = chunk.get("choices", []) if isinstance(chunk, dict) else []
                    if not isinstance(choices, list) or not choices:
                        continue
                    choice = choices[0] if isinstance(choices[0], dict) else {}
                    delta = choice.get("delta", {}) if isinstance(choice.get("delta"), dict) else {}
                    content = delta.get("content")
                    if content:
                        text = str(content)
                        text_parts.append(text)
                        try:
                            on_chunk(text)
                        except Exception:
                            pass
                        if watchdog.push(text):
                            return {"error": "model output repetition loop detected", "_lah_repetition_loop_detected": True, "_lah_provider": "llama.cpp-sycl"}
                    for tool in delta.get("tool_calls", []) if isinstance(delta.get("tool_calls"), list) else []:
                        if not isinstance(tool, dict):
                            continue
                        index = int(tool.get("index", 0) or 0)
                        accumulated = tool_state.setdefault(index, {"id": "", "function": {"name": "", "arguments": ""}})
                        if tool.get("id"):
                            accumulated["id"] = str(tool["id"])
                        fn = tool.get("function", {})
                        if isinstance(fn, dict):
                            if fn.get("name"):
                                accumulated["function"]["name"] += str(fn["name"])
                            if fn.get("arguments"):
                                accumulated["function"]["arguments"] += str(fn["arguments"])
                    if choice.get("finish_reason"):
                        finish_reason = str(choice["finish_reason"])
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            return {"error": f"llama.cpp HTTP {exc.code}: {detail}", "_lah_provider": "llama.cpp-sycl"}
        except (URLError, socket.timeout, TimeoutError) as exc:
            return {"error": f"llama.cpp request failed: {exc}", "_lah_provider": "llama.cpp-sycl"}
        except Exception as exc:
            return {"error": f"llama.cpp request failed: {type(exc).__name__}: {exc}", "_lah_provider": "llama.cpp-sycl"}

        text = "".join(text_parts)
        result: dict[str, Any] = {
            "done": True,
            "response": text,
            "prompt_eval_count": prompt_tokens,
            "eval_count": output_tokens,
            "_lah_retry_count": 0,
            "_lah_provider": "llama.cpp-sycl",
        }
        if endpoint == "/api/chat":
            result["message"] = {"role": "assistant", "content": text}
            if tool_state:
                result["message"]["tool_calls"] = self._tool_calls(tool_state)
        if finish_reason:
            result["done_reason"] = finish_reason
        return result
