"""Deferred native recovery regressions: fake transport/processes and tmp state."""
import copy
import json
import threading
import time
from contextlib import nullcontext
from io import BytesIO
from types import SimpleNamespace

import pytest

from local_ai_hub import llama_cpp as module
from local_ai_hub.llama_cpp_runtime import LlamaCppManagedRuntime
from local_ai_hub.ollama import OllamaRuntime
from local_ai_hub.llm_context_recovery import fit_recovered_context, recovery_route


def _router(monkeypatch, results, managed=True):
    config = {"llama_cpp": {"mode": "on", "models": {"fake": {
        "url": "http://127.0.0.1:12438", "served_model": "original", "context_length": 8192,
    }}}}
    fallback = recovery_route("fake", config["llama_cpp"]["models"]["fake"])
    manager = SimpleNamespace(recovery_entry=lambda model: copy.deepcopy(fallback)) if managed else None
    router = module.LlamaCppRouter(config, managed_runtime=manager)
    calls = []

    def attempt(endpoint, payload, *args):
        calls.append((copy.deepcopy(payload), router._entry("fake")[0], args[-1]))
        return copy.deepcopy(results.pop(0))

    monkeypatch.setattr(router, "_request_stream_once", attempt)
    monkeypatch.setattr(router, "_quiesce_for_recovery", lambda *args: True)
    return router, calls, fallback


@pytest.mark.parametrize("first", [
    {"error": "SYCL out of memory"}, {"error": "load failed", "model_load_failed": True},
])
def test_native_recovery_switches_real_preset_once_and_reuses_it(monkeypatch, first):
    router, calls, fallback = _router(monkeypatch, [first, {"done": True, "response": "ok"}, {"done": True, "response": "again"}])
    payload = {"model": "fake", "prompt": "small input", "options": {"num_ctx": 8192, "num_predict": 32}}
    original_payload, original_config = copy.deepcopy(payload), copy.deepcopy(router.config)
    result = router.request_stream("/api/generate", payload, None, timeout=5)
    assert result["done"] and result["_lah_retry_count"] == 1
    assert [call[0]["options"]["num_ctx"] for call in calls] == [8192, 4096]
    assert [call[1]["served_model"] for call in calls] == ["original", fallback["served_model"]]
    assert calls[0][2] == calls[1][2]
    assert not result["context_recovery"]["input_truncated"]
    reused = router.request_stream("/api/generate", payload, None, timeout=5)
    assert reused["response"] == "again" and calls[-1][1]["served_model"] == fallback["served_model"]
    assert payload == original_payload and router.config == original_config
    monkeypatch.setattr(router, "_unload_model_once", lambda *args, **kwargs: True)
    assert router.unload_model("fake")
    assert router._entry("fake")[0]["served_model"] == "original"
    router._active_recoveries["fake"] = fallback
    assert router.unload_model("original")
    assert not router._active_recoveries


@pytest.mark.parametrize("first", [
    {"error": "SYCL out of memory", "_lah_partial_response": True},
    {"error": "SYCL out of memory", "timed_out": True},
    {"error": "SYCL out of memory", "preempted": True},
    {"error": "SYCL out of memory", "outcome_unknown": True},
    {"error": "connection refused"},
])
def test_non_replayable_or_unrelated_errors_never_switch_preset(monkeypatch, first):
    router, calls, _fallback = _router(monkeypatch, [first])
    assert router.request_stream("/api/generate", {"model": "fake", "prompt": "x"}, None)["error"] == first["error"]
    assert len(calls) == 1 and not router._active_recoveries


def test_unmanaged_provider_never_receives_managed_recovery(monkeypatch):
    router, calls, _fallback = _router(monkeypatch, [{"error": "out of memory"}], managed=False)
    router.request_stream("/api/generate", {"model": "fake", "prompt": "x"}, None)
    assert len(calls) == 1


def test_unconfirmed_unload_stops_before_second_provider_attempt(monkeypatch):
    router, calls, _fallback = _router(monkeypatch, [{"error": "out of memory"}])
    monkeypatch.setattr(router, "_quiesce_for_recovery", lambda *args: False)
    result = router.request_stream("/api/generate", {"model": "fake", "prompt": "x"}, None)
    assert result["outcome_unknown"] and result["cleanup_unconfirmed"]
    assert not result["retryable"] and len(calls) == 1


def test_large_input_refuses_recovery_before_unload(monkeypatch):
    router, calls, _fallback = _router(monkeypatch, [{"error": "out of memory"}])
    monkeypatch.setattr(router, "_quiesce_for_recovery", lambda *args: pytest.fail("oversized input caused unload"))
    result = router.request_stream("/api/generate", {"model": "fake", "prompt": "x" * 5000}, None)
    assert result["context_recovery"]["reason"] == "retained_input_exceeds_reduced_budget"
    assert len(calls) == 1


def test_native_transport_uses_recovery_alias_in_actual_openai_request(monkeypatch):
    router, _calls, fallback = _router(monkeypatch, [])
    monkeypatch.setattr(router, "_request_stream_once", module.LlamaCppRouter._request_stream_once.__get__(router))
    monkeypatch.setattr(router, "ensure_model", lambda *args, **kwargs: True)
    bodies = []
    events = [[{"error": "SYCL out of memory"}], [{"choices": [{"delta": {"content": "ok"}}]}, "[DONE]"]]

    def open_response(request, *args):
        bodies.append(json.loads(request.data))
        data = events.pop(0)
        return BytesIO(b"".join(b"data: " + (item.encode() if isinstance(item, str) else json.dumps(item).encode()) + b"\n\n" for item in data))

    monkeypatch.setattr(module, "_open_interruptible_response", open_response)
    monkeypatch.setattr(module, "_cancel_response_on_stop", lambda *args: nullcontext())
    result = router.request_stream("/api/generate", {"model": "fake", "prompt": "x"}, None)
    assert result["response"] == "ok"
    assert [body["model"] for body in bodies] == ["original", fallback["served_model"]]
    assert bodies[0]["messages"] == bodies[1]["messages"]


def test_preset_recovery_binds_to_held_process_generation(tmp_path):
    config = {"server": {"state_dir": str(tmp_path)}, "llama_cpp": {"models": {"fake": {
        "url": "http://127.0.0.1:12438", "served_model": "original", "context_length": 8192,
    }}}}
    original = copy.deepcopy(config)
    runtime = LlamaCppManagedRuntime(config)
    runtime._write_preset()
    fallback = runtime._recovery_routes["fake"]
    preset = (runtime.runtime_dir / "hub.models.ini").read_text(encoding="utf-8")
    assert f"[{fallback['served_model']}]" in preset and "ctx-size = 4096" in preset
    assert preset.count(f'model = "{str(runtime.model_path.resolve()).replace(chr(92), "/")}"') == 2
    assert runtime.recovery_entry("fake") is None
    process = SimpleNamespace(poll=lambda: None)
    runtime._managed_process = runtime._recovery_process = process
    runtime._prepared_recovery_routes = copy.deepcopy(runtime._recovery_routes)
    assert runtime.recovery_entry("fake")["context_length"] == 4096
    runtime._managed_process = SimpleNamespace(poll=lambda: None)
    assert runtime.recovery_entry("fake") is None
    assert config == original


def test_recovery_budget_includes_tools_and_refuses_unknown_vision_cost():
    adjusted, metadata = fit_recovered_context({"prompt": "x", "tools": [{"schema": "x" * 5000}]}, 8192, 4096)
    assert adjusted is None and metadata["reason"] == "retained_input_exceeds_reduced_budget"
    adjusted, metadata = fit_recovered_context({"prompt": "x", "images": ["small-compressed-image"]}, 8192, 4096)
    assert adjusted is None and metadata["reason"] == "multimodal_input_budget_unknown"


def test_managed_generation_slot_serializes_requests_and_remains_cancellable(monkeypatch):
    router, _calls, _fallback = _router(monkeypatch, [])
    entered, release, waiting = threading.Event(), threading.Event(), threading.Event()
    calls, results = [], []

    def attempt(endpoint, payload, *args):
        calls.append(payload["prompt"])
        if payload["prompt"] == "first":
            entered.set()
            assert release.wait(5)
        return {"done": True, "response": "ok"}

    monkeypatch.setattr(router, "_request_stream_once", attempt)

    def should_stop():
        waiting.set()
        return False

    first = threading.Thread(target=lambda: results.append(router.request_stream("/api/generate", {"model": "fake", "prompt": "first"}, None, timeout=5)), daemon=True)
    second = threading.Thread(target=lambda: results.append(router.request_stream("/api/generate", {"model": "fake", "prompt": "second"}, None, timeout=5, should_stop=should_stop)), daemon=True)
    try:
        first.start()
        assert entered.wait(2)
        second.start()
        assert waiting.wait(2)
        assert calls == ["first"]
    finally:
        release.set()
        first.join(2)
        if second.ident is not None:
            second.join(2)
    assert not first.is_alive() and not second.is_alive()
    assert calls == ["first", "second"] and all(result["done"] for result in results)
    assert router.request_stream("/api/generate", {"model": "fake", "prompt": "cancel"}, None, should_stop=lambda: True)["preempted"]
    assert calls == ["first", "second"]


def test_quiescence_requires_post_unload_provider_state(monkeypatch):
    router, _calls, _fallback = _router(monkeypatch, [])
    monkeypatch.setattr(router, "_quiesce_for_recovery", module.LlamaCppRouter._quiesce_for_recovery.__get__(router))
    states = ["loaded", "unloaded"]
    monkeypatch.setattr(router, "_model_info", lambda *args, **kwargs: {"original": {"status": {"value": states.pop(0)}}})
    monkeypatch.setattr(router, "_unload_model_once", lambda *args, **kwargs: True)
    assert router._quiesce_for_recovery("fake", "http://127.0.0.1:12438", time.monotonic() + 5, None)
    monkeypatch.setattr(router, "_model_info", lambda *args, **kwargs: {"original": {"status": {"value": "loading"}}})
    assert not router._quiesce_for_recovery("fake", "http://127.0.0.1:12438", time.monotonic() + 5, None)


def test_recovery_inventory_and_unload_preserve_owner_bound_alias_identity(monkeypatch):
    router, _calls, fallback = _router(monkeypatch, [])
    router._active_recoveries["fake"] = fallback
    monkeypatch.setattr(router, "_model_info", lambda *args, **kwargs: {fallback["served_model"]: {"status": {"value": "loaded"}}})
    snapshot = router.loaded_model_inventory(force_refresh=True)
    assert snapshot["complete"]
    row = snapshot["models"][0]
    assert row["name"] == "original" and row["served_model"] == fallback["served_model"]
    runtime = object.__new__(OllamaRuntime)
    runtime.llama_cpp = router
    unloaded = []
    monkeypatch.setattr(router, "unload_model", lambda name, **kwargs: unloaded.append(name) or True)
    assert runtime.unload_inventory_model(row)
    assert unloaded == [fallback["served_model"]]
    assert not runtime.unload_inventory_model({**row, "served_model": "foreign"})
    router.managed_runtime.recovery_entry = lambda model: None
    assert router._entry("fake")[0]["served_model"] == "original"
    assert not runtime.unload_inventory_model(row)
    assert len(unloaded) == 1


def test_shared_alias_reuses_same_recovery_and_rejects_conflicting_context(tmp_path, monkeypatch):
    router, _calls, fallback = _router(monkeypatch, [])
    router.settings["models"]["other"] = copy.deepcopy(router.settings["models"]["fake"])
    router._active_recoveries["fake"] = fallback
    assert router._entry("other")[0]["served_model"] == fallback["served_model"]
    monkeypatch.setattr(router, "_unload_model_once", lambda *args, **kwargs: True)
    assert router.unload_model("other") and not router._active_recoveries
    config = {"server": {"state_dir": str(tmp_path)}, "llama_cpp": router.settings}
    runtime = LlamaCppManagedRuntime(config)
    runtime._write_preset()
    assert runtime._recovery_routes["fake"]["served_model"] == runtime._recovery_routes["other"]["served_model"]
    original_preset = (runtime.runtime_dir / "hub.models.ini").read_bytes()
    router.settings["models"]["other"]["context_length"] = 16384
    with pytest.raises(ValueError, match="Conflicting context_length"):
        runtime._write_preset()
    assert (runtime.runtime_dir / "hub.models.ini").read_bytes() == original_preset


def test_excluded_vision_route_does_not_change_managed_text_server_port(tmp_path):
    runtime = LlamaCppManagedRuntime({"server": {"state_dir": str(tmp_path)}, "llama_cpp": {"models": {
        "text": {"url": "http://127.0.0.1:12438", "served_model": "text"},
        "qwen3-vl:4b": {"url": "http://127.0.0.1:12439", "served_model": "vision"},
    }}})
    assert runtime._port_and_url() == (12438, "http://127.0.0.1:12438")
