from __future__ import annotations

from pathlib import Path


class FakeRuntime:
    def __init__(self, loaded: list[dict] | None = None):
        self.loaded = list(loaded or [])
        self.events: list[tuple] = []

    def is_online(self) -> bool:
        return True

    def ensure_running(self) -> bool:
        self.events.append(("ensure_running",))
        return True

    def request(self, endpoint: str, payload: dict | None = None, timeout: float | None = None) -> dict:
        self.events.append(("request", endpoint, (payload or {}).get("model")))
        return {"done": True}

    def request_interruptible(self, endpoint: str, payload: dict | None, should_stop, *, timeout: float | None = None) -> dict:
        return self.request(endpoint, payload, timeout)

    def prepare_model(self, model: str, *, unload_others: bool = True) -> list[str]:
        self.events.append(("prepare_model", model, unload_others))
        return []

    def unload(self, model: str) -> bool:
        return self.unload_model(model)

    def unload_model(self, model: str) -> bool:
        self.events.append(("unload_model", model))
        self.loaded = [row for row in self.loaded if row.get("name") != model]
        return True

    def loaded_models(self) -> list[str]:
        return [str(row.get("name", "")) for row in self.loaded]

    def loaded_model_details(self) -> list[dict]:
        return list(self.loaded)

    def version(self) -> str:
        return "test"

    def installed_models(self) -> list[str]:
        return []

    def managed_profile_status(self) -> dict:
        return {"managed": False, "url": "http://fake"}

    def stop_managed_server(self) -> bool:
        self.events.append(("stop_managed_server",))
        return True


def _config(tmp_path: Path) -> dict:
    return {
        "server": {"ollama_url": "http://127.0.0.1:11434", "state_dir": str(tmp_path)},
        "models": {"fast_code": "qwen2.5-coder:7b", "heavy_code": "qwen3.5:9b", "reasoning": "qwen3.5:9b"},
        "model_execution": {"fast": {"parallel": 2}, "smart": {"parallel": 1, "context_tokens": 32768}},
        "smart_ollama": {"enabled": True, "url": "http://127.0.0.1:11437", "model": "qwen3.5:9b"},
    }


def test_smart_request_unloads_fast_runner_before_dispatch(tmp_path: Path):
    from local_ai_hub.tiered_ollama import TieredOllamaRuntime

    fast = FakeRuntime([{"name": "qwen2.5-coder:7b"}])
    smart = FakeRuntime()
    runtime = TieredOllamaRuntime(_config(tmp_path), fast_runtime=fast, smart_runtime=smart)

    result = runtime.request("/api/generate", {"model": "qwen3.5:9b"})

    assert result["done"] is True
    assert fast.events == [("unload_model", "qwen2.5-coder:7b")]
    assert smart.events == [("ensure_running",), ("request", "/api/generate", "qwen3.5:9b")]


def test_fast_request_unloads_smart_runner_before_prepare(tmp_path: Path):
    from local_ai_hub.tiered_ollama import TieredOllamaRuntime

    fast = FakeRuntime()
    smart = FakeRuntime([{"name": "qwen3.5:9b"}])
    runtime = TieredOllamaRuntime(_config(tmp_path), fast_runtime=fast, smart_runtime=smart)

    runtime.prepare_model("qwen2.5-coder:7b")

    assert smart.events == [("unload_model", "qwen3.5:9b")]
    assert fast.events == [("ensure_running",), ("prepare_model", "qwen2.5-coder:7b", True)]


def test_status_keeps_endpoint_ownership_and_handoff_metadata(tmp_path: Path):
    from local_ai_hub.tiered_ollama import TieredOllamaRuntime

    runtime = TieredOllamaRuntime(_config(tmp_path), fast_runtime=FakeRuntime(), smart_runtime=FakeRuntime())
    status = runtime.managed_profile_status()

    assert status["fast"]["url"] == "http://fake"
    assert status["smart"]["url"] == "http://fake"
    assert status["smart"]["owned"] is True
    assert status["handoff"]["count"] == 0


def test_smart_request_does_not_unload_unknown_external_model(tmp_path: Path):
    from local_ai_hub.tiered_ollama import TieredOllamaRuntime

    fast = FakeRuntime([{"name": "user-owned-model"}])
    smart = FakeRuntime()
    runtime = TieredOllamaRuntime(_config(tmp_path), fast_runtime=fast, smart_runtime=smart)

    result = runtime.request("/api/generate", {"model": "qwen3.5:9b"})

    assert result["retryable"] is True
    assert fast.events == []
    assert smart.events == [("ensure_running",)]
