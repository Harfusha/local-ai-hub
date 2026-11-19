from types import SimpleNamespace

import pytest

from local_ai_hub.ollama import OllamaRuntime


def _runtime(tmp_path, mode, fallback):
    runtime = OllamaRuntime({
        "server": {"ollama_url": "http://127.0.0.1:11434", "state_dir": str(tmp_path)},
        "ollama": {"enabled": True},
        "llama_cpp": {
            "mode": mode,
            "fallback_to_ollama": fallback,
            "models": {"qwen2.5-coder:3b": {"url": "http://127.0.0.1:12438"}},
        },
    })
    runtime.llama_cpp.ensure_model = lambda *args, **kwargs: False
    runtime.is_online = lambda: True
    runtime.model_policy = SimpleNamespace(profile=lambda model: SimpleNamespace(num_ctx=4096))
    calls = []
    runtime.request = lambda path, payload, **kwargs: calls.append((path, payload)) or {"done": True}
    runtime.loaded_model_details = lambda **kwargs: (
        [{"name": "qwen2.5-coder:3b", "size_bytes": 1024, "vram_bytes": 1024, "cpu_bytes": 0}]
        if calls else []
    )
    return runtime, calls


def test_disabled_llama_does_not_block_ollama_or_admission(tmp_path):
    runtime, calls = _runtime(tmp_path, "off", False)
    assert runtime.ensure_running() is True
    assert runtime.supports_post_unload_admission("qwen2.5-coder:3b") is True
    assert runtime.prepare_model("qwen2.5-coder:3b", post_unload_admission=lambda: {"state": "admitted"}) == []
    assert [path for path, _ in calls] == ["/api/generate"]


def test_post_unload_admission_not_available_without_enabled_backend(tmp_path):
    runtime, _ = _runtime(tmp_path, "off", False)
    runtime.config["ollama"]["enabled"] = False
    assert runtime.supports_post_unload_admission("qwen2.5-coder:3b") is False


@pytest.mark.parametrize("mode", ["on", "auto"])
def test_enabled_llama_without_fallback_still_fails_closed(tmp_path, mode):
    runtime, calls = _runtime(tmp_path, mode, False)
    assert runtime.ensure_running() is False
    with pytest.raises(RuntimeError, match="configured llama.cpp"):
        runtime.prepare_model("qwen2.5-coder:3b")
    assert calls == []


@pytest.mark.parametrize("mode", ["on", "auto"])
def test_enabled_llama_with_fallback_can_use_ollama(tmp_path, mode):
    runtime, calls = _runtime(tmp_path, mode, True)
    assert runtime.ensure_running() is True
    assert runtime.prepare_model("qwen2.5-coder:3b") == []
    assert [path for path, _ in calls] == ["/api/generate"]
