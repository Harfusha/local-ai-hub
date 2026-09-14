from __future__ import annotations

import copy
import threading
import time
from typing import Any

from .model_policy import ModelExecutionPolicy
from .ollama import OllamaRuntime


class TieredOllamaRuntime:
    """Route smart models through a Hub-owned Ollama sidecar.

    The external runtime stays user-managed. This facade owns only the smart
    runtime and serializes model residency across both endpoints.
    """

    def __init__(
        self,
        config: dict[str, Any],
        *,
        fast_runtime: Any | None = None,
        smart_runtime: Any | None = None,
    ) -> None:
        self.config = config
        self.policy = ModelExecutionPolicy(config)
        self.fast = fast_runtime or OllamaRuntime(config)
        self.smart = smart_runtime or OllamaRuntime(self._smart_config(), managed_name="ollama-smart")
        self._lock = threading.RLock()
        self._handoff_count = 0
        self._unload_failures = 0
        self._last_handoff_error: str | None = None
        self._active_endpoint: str | None = None
        self._hub_models = {str(model) for model in config.get("models", {}).values() if str(model or "")}

    def _smart_config(self) -> dict[str, Any]:
        smart_cfg = self.config.get("smart_ollama", {})
        cfg = copy.deepcopy(self.config)
        cfg.setdefault("server", {})["ollama_url"] = str(smart_cfg.get("url", "http://127.0.0.1:11437")).rstrip("/")
        cfg.setdefault("headless", {})["autostart_ollama"] = True
        cfg.setdefault("scheduler", {})["max_parallel"] = 1
        cfg["scheduler"]["max_loaded_models"] = 1
        ollama = cfg.setdefault("ollama", {})
        ollama["num_parallel"] = max(1, int(smart_cfg.get("num_parallel", 1)))
        ollama["keep_alive"] = str(smart_cfg.get("keep_alive", "10m"))
        ollama["flash_attention"] = bool(smart_cfg.get("flash_attention", True))
        ollama["kv_cache_type"] = str(smart_cfg.get("kv_cache_type", "q8_0"))
        ollama["startup_timeout_seconds"] = float(smart_cfg.get("startup_timeout_seconds", 30))
        model = str(smart_cfg.get("model") or cfg.get("models", {}).get("heavy_code", ""))
        if model:
            cfg.setdefault("models", {})["heavy_code"] = model
            cfg["models"]["reasoning"] = model
        execution = cfg.setdefault("model_execution", {}).setdefault("smart", {})
        context = max(4096, int(smart_cfg.get("context_length", 32768)))
        execution["context_tokens"] = context
        execution["large_context_tokens"] = context
        execution["max_context_tokens"] = context
        execution["parallel"] = 1
        return cfg

    def _runtime_for_model(self, model: str) -> tuple[str, Any, Any]:
        if self.policy.tier_for(model) == "smart":
            return "smart", self.smart, self.fast
        return "fast", self.fast, self.smart

    @staticmethod
    def _details(runtime: Any) -> list[dict[str, Any]]:
        try:
            rows = runtime.loaded_model_details()
        except Exception:
            return []
        return [row for row in rows if isinstance(row, dict)]

    def _unload_peer(self, peer: Any) -> None:
        rows = self._details(peer)
        foreign = [str(row.get("name", "")) for row in rows if str(row.get("name", "")) not in self._hub_models]
        if foreign:
            self._last_handoff_error = f"peer runtime holds externally managed model: {foreign[0]}"
            raise RuntimeError(self._last_handoff_error)
        for row in rows:
            model = str(row.get("name", "") or "")
            if model and not peer.unload_model(model):
                self._unload_failures += 1
                self._last_handoff_error = f"cannot unload {model} from peer runtime"
                raise RuntimeError(self._last_handoff_error)

    def _handoff(self, name: str, target: Any, peer: Any) -> None:
        if not target.ensure_running():
            self._last_handoff_error = f"{name} runtime unavailable"
            raise RuntimeError(self._last_handoff_error)
        self._unload_peer(peer)
        timeout = max(0.1, float(self.config.get("smart_ollama", {}).get("handoff_timeout_seconds", 10)))
        deadline = time.monotonic() + timeout
        while self._details(peer):
            if time.monotonic() >= deadline:
                self._unload_failures += 1
                self._last_handoff_error = "peer runtime remained loaded after handoff deadline"
                raise RuntimeError(self._last_handoff_error)
            time.sleep(0.05)
        self._handoff_count += 1
        self._last_handoff_error = None
        self._active_endpoint = name

    def _target(self, model: str) -> tuple[Any, str]:
        name, target, peer = self._runtime_for_model(model)
        self._handoff(name, target, peer)
        return target, name

    def request(self, endpoint: str, payload: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
        model = str((payload or {}).get("model", ""))
        if not model:
            return self.fast.request(endpoint, payload, timeout)
        with self._lock:
            try:
                target, _ = self._target(model)
            except RuntimeError as exc:
                return {"error": str(exc), "retryable": True}
            return target.request(endpoint, payload, timeout)

    def request_stream(self, endpoint: str, payload: dict[str, Any] | None, on_chunk: Any, timeout: float | None = None) -> dict[str, Any]:
        model = str((payload or {}).get("model", ""))
        if not model:
            return self.fast.request_stream(endpoint, payload, on_chunk, timeout)
        with self._lock:
            try:
                target, _ = self._target(model)
            except RuntimeError as exc:
                return {"error": str(exc), "retryable": True}
            return target.request_stream(endpoint, payload, on_chunk, timeout)

    def request_interruptible(self, endpoint: str, payload: dict[str, Any] | None, should_stop: Any, *, timeout: float | None = None) -> dict[str, Any]:
        model = str((payload or {}).get("model", ""))
        with self._lock:
            try:
                target, _ = self._target(model)
            except RuntimeError as exc:
                return {"error": str(exc), "retryable": True}
            return target.request_interruptible(endpoint, payload, should_stop, timeout=timeout)

    def prepare_model(self, model: str, *, unload_others: bool = True) -> list[str]:
        with self._lock:
            target, _ = self._target(model)
            return target.prepare_model(model, unload_others=unload_others)

    def unload(self, model: str) -> bool:
        return self.unload_model(model)

    def unload_model(self, model: str) -> bool:
        _, target, _ = self._runtime_for_model(model)
        return bool(target.unload_model(model))

    def is_online(self) -> bool:
        return bool(self.fast.is_online() or self.smart.is_online())

    def ensure_running(self) -> bool:
        return bool(self.fast.ensure_running())

    def version(self) -> str | None:
        return self.fast.version()

    def installed_models(self) -> list[str]:
        return self.fast.installed_models()

    def loaded_model_details(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for endpoint, runtime in (("fast", self.fast), ("smart", self.smart)):
            for row in self._details(runtime):
                item = dict(row)
                item["endpoint"] = endpoint
                rows.append(item)
        return rows

    def loaded_models(self) -> list[str]:
        return [str(row.get("name", "")) for row in self.loaded_model_details() if row.get("name")]

    def managed_profile_status(self) -> dict[str, Any]:
        fast = dict(self.fast.managed_profile_status())
        smart = dict(self.smart.managed_profile_status())
        smart["owned"] = True
        return {
            "fast": fast,
            "smart": smart,
            "handoff": {
                "count": self._handoff_count,
                "unload_failures": self._unload_failures,
                "active_endpoint": self._active_endpoint,
                "last_error": self._last_handoff_error,
            },
        }

    def stop_managed_server(self) -> bool:
        return bool(self.smart.stop_managed_server())

    def generate(self, model: str, prompt: str, **kwargs: Any) -> dict[str, Any]:
        payload = {"model": model, "prompt": prompt, "stream": False, **kwargs}
        return self.request("/api/generate", payload)

    def chat(self, model: str, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        payload = {"model": model, "messages": messages, "stream": False, **kwargs}
        return self.request("/api/chat", payload)

    def embeddings(self, model: str, prompt: str) -> dict[str, Any]:
        return self.request("/api/embeddings", {"model": model, "prompt": prompt})

    def evict_if_needed(self, required_model: str) -> bool:
        _, target, peer = self._runtime_for_model(required_model)
        try:
            self._unload_peer(peer)
        except RuntimeError:
            return False
        return bool(target.evict_if_needed(required_model))
