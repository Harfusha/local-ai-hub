from __future__ import annotations

import time
from pathlib import Path

import pytest

from local_ai_hub.ollama import OllamaRuntime


def _runtime(tmp_path: Path) -> OllamaRuntime:
    return OllamaRuntime(
        {
            "server": {
                "state_dir": str(tmp_path),
                "ollama_url": "http://127.0.0.1:11434",
                "request_timeout_seconds": 1.0,
            },
            "ollama": {"enabled": True, "request_attempts": 1},
            "models": {
                "fast_code": "configured-fast",
                "heavy_code": "configured-heavy",
                "embedding": "configured-embedding",
                "embedding_backend": "sentence-transformers",
                "embedding_device": "cpu",
            },
            "ollama_subagents": {
                "profiles": {"drafter": {"model": "configured-subagent"}},
            },
            "llama_cpp": {"fallback_to_ollama": True, "models": {}},
        }
    )


def _assert_pause_result(
    result: dict,
    *,
    success: bool,
    backend_available: bool,
    requested: list[str],
    unloaded: list[str],
    remaining: list[str] | None,
    failed: dict[str, str],
    verified: bool,
    complete: bool,
    unverified: bool,
    inventory_status: str = "complete",
) -> None:
    assert result["success"] is success
    assert result["backend_available"] is backend_available
    assert result["requested"] == requested
    assert result["unloaded"] == unloaded
    assert result["remaining"] == remaining
    assert result["requested_by_backend"] == {"ollama": requested}
    assert result["remaining_by_backend"] == {"ollama": remaining}
    assert result["backend_inventory_status"] == {"ollama": {"ollama": inventory_status}}
    assert result["failed"] == failed
    assert result["verified"] is verified
    assert result["complete"] is complete
    assert result["unverified"] is unverified
    assert result["physical_vram_reclaimed"] is False


def test_pause_unloads_every_loaded_model_without_loading_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(tmp_path)
    requests: list[tuple[str, dict | None, float | None, float | None]] = []
    loaded = ["configured-fast", "configured-subagent", "unconfigured-external"]

    def request(endpoint, payload=None, timeout=None, *, should_stop=None, deadline=None):
        requests.append((endpoint, payload, timeout, deadline))
        if endpoint == "/api/ps":
            return {"models": [{"name": name} for name in loaded]}
        if endpoint == "/api/generate":
            loaded.remove(payload["model"])
            return {"done": True, "done_reason": "unload"}
        pytest.fail(f"pause must not call {endpoint}")

    monkeypatch.setattr(runtime, "request", request)
    monkeypatch.setattr(runtime, "load_model", lambda *_a, **_k: pytest.fail("pause must not load a model"))
    monkeypatch.setattr(runtime, "ensure_running", lambda *_a, **_k: pytest.fail("pause must not start a backend"))

    result = runtime.unload_configured_models(timeout_seconds=0.5)

    expected = ["configured-fast", "configured-subagent", "unconfigured-external"]
    _assert_pause_result(
        result, success=True, backend_available=True, requested=expected, unloaded=expected,
        remaining=[], failed={}, verified=True, complete=True, unverified=False,
    )
    unloads = [(endpoint, payload) for endpoint, payload, _timeout, _deadline in requests if endpoint != "/api/ps"]
    assert [endpoint for endpoint, _payload in unloads] == ["/api/generate", "/api/generate", "/api/generate"]
    assert [payload["model"] for _endpoint, payload in unloads] == [
        "configured-fast", "configured-subagent", "unconfigured-external",
    ]
    assert all(payload.get("prompt", "") == "" for _endpoint, payload in unloads)
    assert all(payload["keep_alive"] == 0 for _endpoint, payload in unloads)
    assert all(deadline is not None for _endpoint, _payload, _timeout, deadline in requests)


def test_pause_does_not_report_unload_without_backend_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(tmp_path)

    loaded = ["configured-fast"]

    def request(endpoint, payload=None, timeout=None, *, should_stop=None, deadline=None):
        if endpoint == "/api/ps":
            return {"models": [{"name": name} for name in loaded]}
        if endpoint == "/api/generate":
            return {"done": True, "done_reason": "stop"}
        pytest.fail(f"pause must not call {endpoint}")

    monkeypatch.setattr(runtime, "request", request)

    result = runtime.unload_configured_models(timeout_seconds=0.5)

    _assert_pause_result(
        result, success=False, backend_available=True, requested=["configured-fast"], unloaded=[],
        remaining=["configured-fast"], failed={"configured-fast": "unload failed or timed out"},
        verified=False, complete=False, unverified=False,
    )


def test_pause_is_idempotent_when_no_models_are_loaded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(tmp_path)
    endpoints: list[str] = []

    def request(endpoint, payload=None, timeout=None, *, should_stop=None, deadline=None):
        endpoints.append(endpoint)
        if endpoint == "/api/ps":
            return {"models": []}
        pytest.fail(f"no model unload is needed; got {endpoint}")

    monkeypatch.setattr(runtime, "request", request)

    first = runtime.unload_configured_models(timeout_seconds=0.5)
    second = runtime.unload_configured_models(timeout_seconds=0.5)

    _assert_pause_result(
        first, success=True, backend_available=True, requested=[], unloaded=[], remaining=[], failed={},
        verified=True, complete=True, unverified=False,
    )
    assert second == first
    assert endpoints == ["/api/ps", "/api/ps", "/api/ps", "/api/ps"]


def test_pause_reports_backend_unavailable_with_a_shared_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(tmp_path)
    calls: list[tuple[str, float | None, float | None]] = []
    started = time.monotonic()

    def request(endpoint, payload=None, timeout=None, *, should_stop=None, deadline=None):
        calls.append((endpoint, timeout, deadline))
        return {"error": "backend unavailable"}

    monkeypatch.setattr(runtime, "request", request)
    monkeypatch.setattr(runtime, "ensure_running", lambda *_a, **_k: pytest.fail("pause must not start a backend"))

    result = runtime.unload_configured_models(timeout_seconds=0.2)

    assert result["success"] is False
    assert result["backend_available"] is False
    assert result["unloaded"] == []
    assert result["requested"] == []
    assert result["remaining"] is None
    assert result["failed"] == {
        "ollama": "backend unavailable",
        "verification": "ollama: post-unload /api/ps unavailable",
    }
    assert result["verified"] is False
    assert result["complete"] is False
    assert result["unverified"] is True
    assert result["physical_vram_reclaimed"] is False
    assert result["backend_inventory_status"] == {"ollama": {"ollama": "unknown"}}
    assert [endpoint for endpoint, _timeout, _deadline in calls] == ["/api/ps", "/api/ps"]
    assert calls[0][1] is not None and calls[0][1] <= 0.2
    assert calls[0][2] is not None and calls[0][2] - started <= 0.25
    assert calls[0][2] == calls[1][2]


def test_pause_reports_unload_timeout_without_loading_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(tmp_path)
    requests: list[tuple[str, dict | None, float | None, float | None]] = []
    loaded = ["configured-fast"]

    def request(endpoint, payload=None, timeout=None, *, should_stop=None, deadline=None):
        requests.append((endpoint, payload, timeout, deadline))
        if endpoint == "/api/ps":
            return {"models": [{"name": name} for name in loaded]}
        return {"error": "unload request timed out", "timed_out": True}

    monkeypatch.setattr(runtime, "request", request)
    monkeypatch.setattr(runtime, "load_model", lambda *_a, **_k: pytest.fail("pause must not load a model"))

    result = runtime.unload_configured_models(timeout_seconds=0.2)

    _assert_pause_result(
        result, success=False, backend_available=True, requested=["configured-fast"], unloaded=[],
        remaining=["configured-fast"], failed={"configured-fast": "unload failed or timed out"},
        verified=False, complete=False, unverified=False,
    )
    assert [endpoint for endpoint, _payload, _timeout, _deadline in requests] == [
        "/api/ps", "/api/generate", "/api/ps",
    ]


def test_pause_reports_partial_failure_and_continues_after_active_model_rejects_unload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(tmp_path)
    requests: list[tuple[str, dict | None, float | None, float | None]] = []
    loaded = ["active-runner:Q4_K_M", "idle-model:latest"]

    def request(endpoint, payload=None, timeout=None, *, should_stop=None, deadline=None):
        requests.append((endpoint, payload, timeout, deadline))
        if endpoint == "/api/ps":
            rows = [{"name": model} for model in loaded]
            if len(requests) == 1:
                rows.extend([{"name": " ", "model": "  "}, None])
            return {
                "models": rows
            }
        if payload["model"] == "active-runner:Q4_K_M":
            return {"error": "runner busy with active inference", "busy": True}
        if payload["model"] == "idle-model:latest":
            loaded.remove("idle-model:latest")
            return {"done": True, "done_reason": "unload"}
        pytest.fail(f"pause must not unload unreported model {payload['model']}")

    monkeypatch.setattr(runtime, "request", request)

    result = runtime.unload_configured_models(timeout_seconds=0.5)

    _assert_pause_result(
        result, success=False, backend_available=True,
        requested=["active-runner:Q4_K_M", "idle-model:latest"],
        unloaded=["idle-model:latest"], remaining=["active-runner:Q4_K_M"],
        failed={
            "active-runner:Q4_K_M": "unload failed or timed out",
            "model_row_2": "loaded model row has no usable name or model",
            "model_row_3": "loaded model row is not an object",
        },
        verified=False, complete=False, unverified=False,
    )
    unloads = [(payload, timeout, deadline) for endpoint, payload, timeout, deadline in requests if endpoint == "/api/generate"]
    assert [payload["model"] for payload, _timeout, _deadline in unloads] == [
        "active-runner:Q4_K_M", "idle-model:latest",
    ]
    assert all(0 < timeout <= 0.5 for _payload, timeout, _deadline in unloads)
    assert len({deadline for _payload, _timeout, deadline in unloads}) == 1
