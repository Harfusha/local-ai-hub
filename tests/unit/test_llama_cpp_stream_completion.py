"""Deferred bundle regressions: memory streams only, no model/server processes."""
import copy
import json
from contextlib import nullcontext
from io import BytesIO

import pytest

from local_ai_hub import llama_cpp as module
from local_ai_hub.llama_cpp_runtime import LlamaCppManagedRuntime


def _call(monkeypatch, events):
    router = module.LlamaCppRouter({"llama_cpp": {"mode": "on", "models": {
        "fake": {"url": "http://127.0.0.1:12438", "served_model": "fake"},
    }}})
    monkeypatch.setattr(router, "ensure_model", lambda *args, **kwargs: True)
    lines = [b"data: " + (event.encode() if isinstance(event, str) else json.dumps(event).encode()) + b"\n\n"
             for event in events]
    monkeypatch.setattr(module, "_open_interruptible_response", lambda *args, **kwargs: BytesIO(b"".join(lines)))
    monkeypatch.setattr(module, "_cancel_response_on_stop", lambda *args, **kwargs: nullcontext())
    chunks, thinking = [], []
    result = router.request_stream("/api/generate", {"model": "fake", "prompt": "x"}, chunks.append,
                                   on_thinking=thinking.append)
    return result, chunks, thinking


@pytest.mark.parametrize("events", [[], ["{"], [42], [{"choices": [{"delta": {"content": "partial"}}]}]])
def test_eof_and_malformed_events_never_report_success(monkeypatch, events):
    result, chunks, _thinking = _call(monkeypatch, events)
    assert result["success"] is False and "error" in result
    assert not result.get("done")
    assert result["_lah_partial_response"] == bool(chunks)
    assert result["retryable"] is False


def test_thinking_then_oom_preserves_partial_status_without_replay(monkeypatch):
    result, chunks, thinking = _call(monkeypatch, [
        {"choices": [{"delta": {"reasoning_content": "reason"}}]}, {"error": "SYCL out of memory"},
    ])
    assert result["_lah_partial_response"] and result["success"] is False
    assert thinking == ["reason"] and chunks == []


@pytest.mark.parametrize("marker", ["[DONE]", {"choices": [{"delta": {}, "finish_reason": "stop"}]}])
def test_explicit_completion_marker_accepts_valid_stream(monkeypatch, marker):
    result, chunks, _thinking = _call(monkeypatch, [
        {"choices": [{"delta": {"content": "ok"}}]}, marker,
    ])
    assert result["done"] is True and result["response"] == "ok"
    assert chunks == ["ok"]


def test_preset_retains_configured_context_without_mutating_config(tmp_path):
    config = {"server": {"state_dir": str(tmp_path)}, "llama_cpp": {"models": {
        "fake": {"served_model": "fake", "url": "http://127.0.0.1:12438", "context_length": 8192},
    }}}
    original = copy.deepcopy(config)
    runtime = LlamaCppManagedRuntime(config)
    runtime._write_preset()
    assert "ctx-size = 8192" in (runtime.runtime_dir / "hub.models.ini").read_text(encoding="utf-8")
    assert config == original


@pytest.mark.parametrize("context", [-1, True, "invalid"])
def test_invalid_preset_context_never_overwrites_existing_preset(tmp_path, context):
    runtime = LlamaCppManagedRuntime({"server": {"state_dir": str(tmp_path)}, "llama_cpp": {"models": {
        "fake": {"served_model": "fake", "url": "http://127.0.0.1:12438", "context_length": context},
    }}})
    runtime.runtime_dir.mkdir(parents=True)
    preset = runtime.runtime_dir / "hub.models.ini"
    preset.write_text("existing", encoding="utf-8")
    with pytest.raises(ValueError):
        runtime._write_preset()
    assert preset.read_text(encoding="utf-8") == "existing"
