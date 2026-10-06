from __future__ import annotations

import time
from pathlib import Path

import pytest

from local_ai_hub.ollama import OllamaRuntime


def test_gaming_pause_unloads_every_loaded_name_and_tag_without_starting_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = OllamaRuntime(
        {
            "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
            "ollama": {"enabled": True, "request_attempts": 1},
            "models": {"fast_code": "configured-fast"},
        }
    )
    rows = [
        {"name": "external/model-q4:Q4_K_M", "model": "external/model-q4:Q4_K_M"},
        {"name": "configured-fast:latest", "model": "configured-fast"},
        {"model": "tag-only:custom"},
        {"name": "prefer-name:Q5_K_M", "model": "prefer-name"},
    ]
    calls: list[tuple[str, dict | None]] = []
    ps_calls = 0

    def request(endpoint, payload=None, timeout=None, *, should_stop=None, deadline=None):
        nonlocal ps_calls
        calls.append((endpoint, payload))
        if endpoint == "/api/ps":
            ps_calls += 1
            return {"models": rows if ps_calls == 1 else []}
        if endpoint == "/api/generate":
            return {"done": True, "done_reason": "unload"}
        pytest.fail(f"gaming pause must not call {endpoint}")

    monkeypatch.setattr(runtime, "request", request)
    monkeypatch.setattr(runtime, "ensure_running", lambda *_a, **_k: pytest.fail("pause must not start a backend"))
    monkeypatch.setattr(runtime, "load_model", lambda *_a, **_k: pytest.fail("pause must not load a model"))

    result = runtime.unload_configured_models(timeout_seconds=0.5)

    expected_models = [
        "external/model-q4:Q4_K_M",
        "configured-fast:latest",
        "tag-only:custom",
        "prefer-name:Q5_K_M",
    ]
    assert result["success"] is True
    assert result["unloaded"] == expected_models
    assert result["requested"] == expected_models
    assert result["remaining"] == []
    assert result["verified"] is True
    assert result["complete"] is True
    assert result["unverified"] is False
    assert result["failed"] == {}
    assert [payload["model"] for endpoint, payload in calls if endpoint == "/api/generate"] == expected_models
    assert all(payload["keep_alive"] == 0 for endpoint, payload in calls if endpoint == "/api/generate")


def test_gaming_pause_forwards_stop_callback_and_absolute_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = OllamaRuntime(
        {
            "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
            "ollama": {"enabled": True, "request_attempts": 1},
            "models": {"fast_code": "configured-fast"},
        }
    )
    stop_check = lambda: False
    deadline = time.monotonic() + 1.0
    calls: list[tuple[str, object, object]] = []
    ps_calls = 0

    def request(endpoint, payload=None, timeout=None, *, should_stop=None, deadline=None):
        nonlocal ps_calls
        calls.append((endpoint, should_stop, deadline))
        if endpoint == "/api/ps":
            ps_calls += 1
            return {"models": [{"name": "external/model:tag"}] if ps_calls == 1 else []}
        if endpoint == "/api/generate":
            return {"done": True, "done_reason": "unload"}
        pytest.fail(f"gaming pause must not call {endpoint}")

    monkeypatch.setattr(runtime, "request", request)

    result = runtime.unload_configured_models(
        timeout_seconds=2.0,
        should_stop=stop_check,
        deadline=deadline,
    )

    assert result["success"] is True
    assert result["unloaded"] == ["external/model:tag"]
    assert result["verified"] is True
    assert result["complete"] is True
    assert calls == [
        ("/api/ps", stop_check, deadline),
        ("/api/generate", stop_check, deadline),
        ("/api/ps", stop_check, deadline),
    ]


def test_gaming_pause_stops_before_query_when_cancelled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = OllamaRuntime(
        {
            "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
            "ollama": {"enabled": True, "request_attempts": 1},
            "models": {"fast_code": "configured-fast"},
        }
    )
    monkeypatch.setattr(
        runtime,
        "request",
        lambda *_a, **_k: pytest.fail("cancelled pause must not query or unload models"),
    )

    result = runtime.unload_configured_models(timeout_seconds=0.5, should_stop=lambda: True)

    assert result["success"] is False
    assert result["cancelled"] is True
    assert result["unloaded"] == []


def test_gaming_pause_reports_exact_remaining_names_when_unload_is_not_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = OllamaRuntime(
        {
            "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
            "ollama": {"enabled": True, "request_attempts": 1},
            "models": {"fast_code": "configured-fast"},
        }
    )
    ps_calls = 0

    def request(endpoint, payload=None, timeout=None, *, should_stop=None, deadline=None):
        nonlocal ps_calls
        if endpoint == "/api/ps":
            ps_calls += 1
            if ps_calls == 1:
                return {"models": [{"name": "configured-fast:Q4_K_M"}]}
            return {"models": [{"name": "configured-fast:Q4_K_M"}, {"name": "external:tag"}]}
        if endpoint == "/api/generate":
            return {"done": True, "done_reason": "unload"}
        pytest.fail(f"gaming pause must not call {endpoint}")

    monkeypatch.setattr(runtime, "request", request)

    result = runtime.unload_configured_models(timeout_seconds=0.5)

    assert result["success"] is False
    assert result["requested"] == ["configured-fast:Q4_K_M"]
    assert result["unloaded"] == []
    assert result["remaining"] == ["configured-fast:Q4_K_M", "external:tag"]
    assert result["verified"] is False
    assert result["complete"] is False
    assert result["unverified"] is False


def test_gaming_pause_marks_post_query_failure_unverified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = OllamaRuntime(
        {
            "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
            "ollama": {"enabled": True, "request_attempts": 1},
            "models": {"fast_code": "configured-fast"},
        }
    )
    ps_calls = 0

    def request(endpoint, payload=None, timeout=None, *, should_stop=None, deadline=None):
        nonlocal ps_calls
        if endpoint == "/api/ps":
            ps_calls += 1
            return {"models": [{"name": "configured-fast:latest"}]} if ps_calls == 1 else {"error": "timeout"}
        if endpoint == "/api/generate":
            return {"done": True, "done_reason": "unload"}
        pytest.fail(f"gaming pause must not call {endpoint}")

    monkeypatch.setattr(runtime, "request", request)

    result = runtime.unload_configured_models(timeout_seconds=0.5)

    assert result["success"] is False
    assert result["requested"] == ["configured-fast:latest"]
    assert result["unloaded"] == []
    assert result["remaining"] is None
    assert result["verified"] is False
    assert result["complete"] is False
    assert result["unverified"] is True


def test_gaming_unloads_both_enabled_backends(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = OllamaRuntime(
        {
            "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
            "ollama": {"enabled": True, "request_attempts": 1},
            "llama_cpp": {"mode": "on", "models": {"llama-model": {"url": "http://127.0.0.1:12438"}}},
            "models": {"fast_code": "ollama-model"},
        }
    )
    ollama_ps = 0
    llama_queries = 0
    llama_unloads: list[str] = []
    calls: list[str] = []

    class FakeLlamaCpp:
        def available_models(self, *, should_stop=None, deadline=None):
            return ["llama-model"]

        def loaded_model_details(self, *, should_stop=None, deadline=None):
            nonlocal llama_queries
            llama_queries += 1
            return [{"name": "llama-model:Q4_K_M"}] if llama_queries == 1 else []

        def unload_model(self, model, *, should_stop=None, deadline=None):
            llama_unloads.append(model)
            return True

    def request(endpoint, payload=None, timeout=None, *, should_stop=None, deadline=None):
        nonlocal ollama_ps
        calls.append(endpoint)
        if endpoint == "/api/ps":
            ollama_ps += 1
            return {"models": [{"name": "ollama-model:latest"}] if ollama_ps == 1 else []}
        if endpoint == "/api/generate":
            return {"done": True, "done_reason": "unload"}
        pytest.fail(f"gaming pause must not call {endpoint}")

    monkeypatch.setattr(runtime, "request", request)
    runtime.llama_cpp = FakeLlamaCpp()

    result = runtime.unload_configured_models(timeout_seconds=0.5)

    assert result["success"] is True
    assert result["requested_by_backend"] == {
        "ollama": ["ollama-model:latest"],
        "llama_cpp": ["llama-model:Q4_K_M"],
    }
    assert result["remaining_by_backend"] == {"ollama": [], "llama_cpp": []}
    assert result["complete"] is True
    assert result["physical_vram_reclaimed"] is False
    assert llama_unloads == ["llama-model:Q4_K_M"]
    assert calls == ["/api/ps", "/api/generate", "/api/ps"]


def test_gaming_unload_continues_other_backend_after_partial_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = OllamaRuntime(
        {
            "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
            "ollama": {"enabled": True, "request_attempts": 1},
            "llama_cpp": {"mode": "on", "models": {"llama-model": {"url": "http://127.0.0.1:12438"}}},
            "models": {"fast_code": "ollama-model"},
        }
    )
    ollama_ps = 0
    llama_queries = 0
    llama_unloads: list[str] = []

    class FakeLlamaCpp:
        def available_models(self, *, should_stop=None, deadline=None):
            return ["llama-model"]

        def loaded_model_details(self, *, should_stop=None, deadline=None):
            nonlocal llama_queries
            llama_queries += 1
            return [{"name": "llama-model:latest"}] if llama_queries == 1 else []

        def unload_model(self, model, *, should_stop=None, deadline=None):
            llama_unloads.append(model)
            return True

    def request(endpoint, payload=None, timeout=None, *, should_stop=None, deadline=None):
        nonlocal ollama_ps
        if endpoint == "/api/ps":
            ollama_ps += 1
            return {"models": [{"name": "ollama-model:latest"}] if ollama_ps == 1 else [{"name": "ollama-model:latest"}]}
        if endpoint == "/api/generate":
            return {"error": "runner rejected unload"}
        pytest.fail(f"gaming pause must not call {endpoint}")

    monkeypatch.setattr(runtime, "request", request)
    runtime.llama_cpp = FakeLlamaCpp()

    result = runtime.unload_configured_models(timeout_seconds=0.5)

    assert result["success"] is False
    assert result["requested_by_backend"]["ollama"] == ["ollama-model:latest"]
    assert result["requested_by_backend"]["llama_cpp"] == ["llama-model:latest"]
    assert result["remaining_by_backend"] == {
        "ollama": ["ollama-model:latest"],
        "llama_cpp": [],
    }
    assert result["verified"] is False
    assert result["complete"] is False
    assert result["failed"]["ollama:ollama-model:latest"] == "unload failed or timed out"
    assert llama_unloads == ["llama-model:latest"]


def test_gaming_auto_backend_discovery_failure_cannot_report_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = OllamaRuntime(
        {
            "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
            "ollama": {"enabled": True, "request_attempts": 1},
            "llama_cpp": {"mode": "auto", "models": {"llama-model": {"url": "http://127.0.0.1:12438"}}},
        }
    )

    class FakeLlamaCpp:
        def available_models(self, *, should_stop=None, deadline=None):
            raise TimeoutError("inventory timed out")

        def loaded_model_details(self, *, should_stop=None, deadline=None):
            return []

        def unload_model(self, *_args, **_kwargs):
            pytest.fail("no model may unload without initial inventory")

    monkeypatch.setattr(runtime, "request", lambda endpoint, *_a, **_k: {"models": []} if endpoint == "/api/ps" else pytest.fail(endpoint))
    runtime.llama_cpp = FakeLlamaCpp()

    result = runtime.unload_configured_models(timeout_seconds=0.5)

    assert result["success"] is False
    assert result["verified"] is False
    assert result["complete"] is False
    assert result["unverified"] is True
    assert result["failed"]
    assert "llama_cpp" in result["failed"]


def test_gaming_post_unload_inventory_timeout_stays_unverified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = OllamaRuntime(
        {
            "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
            "ollama": {"enabled": True, "request_attempts": 1},
            "llama_cpp": {"mode": "on", "models": {"llama-model": {"url": "http://127.0.0.1:12438"}}},
        }
    )
    llama_queries = 0
    ollama_queries = 0

    class FakeLlamaCpp:
        def available_models(self, *, should_stop=None, deadline=None):
            return ["llama-model"]

        def loaded_model_details(self, *, should_stop=None, deadline=None):
            nonlocal llama_queries
            llama_queries += 1
            if llama_queries == 1:
                return [{"name": "llama-model:latest"}]
            raise TimeoutError("post-unload inventory timed out")

        def unload_model(self, model, *, should_stop=None, deadline=None):
            return True

    def request(endpoint, payload=None, **_kwargs):
        nonlocal ollama_queries
        if endpoint == "/api/ps":
            ollama_queries += 1
            return {"models": []}
        if endpoint == "/api/generate":
            return {"done": True, "done_reason": "unload"}
        pytest.fail(endpoint)

    monkeypatch.setattr(runtime, "request", request)
    runtime.llama_cpp = FakeLlamaCpp()

    result = runtime.unload_configured_models(timeout_seconds=0.5)

    assert result["success"] is False
    assert result["requested"] == ["llama-model:latest"]
    assert result["remaining"] is None
    assert result["verified"] is False
    assert result["complete"] is False
    assert result["unverified"] is True
