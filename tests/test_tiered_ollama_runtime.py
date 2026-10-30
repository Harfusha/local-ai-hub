from __future__ import annotations

from pathlib import Path
import threading
import time


class FakeRuntime:
    def __init__(
        self,
        loaded: list[dict] | None = None,
        *,
        post_unload_admission: bool = False,
        inventory_complete: bool = True,
    ):
        self.loaded = list(loaded or [])
        self.post_unload_admission = post_unload_admission
        self.inventory_complete = inventory_complete
        self.events: list[tuple] = []
        self.online = True
        self.prepare_controls: list[tuple] = []
        self.request_controls: list[tuple] = []

    def is_online(self) -> bool:
        return self.online

    def ensure_running(self) -> bool:
        self.events.append(("ensure_running",))
        return True

    def request(self, endpoint: str, payload: dict | None = None, timeout: float | None = None) -> dict:
        if endpoint == "/api/ps":
            if not self.online:
                return {"error": "offline"}
            return {"models": list(self.loaded)}
        self.events.append(("request", endpoint, (payload or {}).get("model")))
        return {"done": True}

    def request_interruptible(self, endpoint: str, payload: dict | None, should_stop, *, timeout: float | None = None, deadline: float | None = None) -> dict:
        self.request_controls.append((should_stop, timeout, deadline))
        return self.request(endpoint, payload, timeout)

    def prepare_model(
        self,
        model: str,
        *,
        unload_others: bool = True,
        post_unload_admission=None,
        should_stop=None,
        deadline: float | None = None,
    ) -> list[str]:
        self.events.append(("prepare_model", model, unload_others))
        self.prepare_controls.append((should_stop, deadline, post_unload_admission))
        return []

    def supports_post_unload_admission(self, model: str) -> bool:
        self.events.append(("supports_post_unload_admission", model))
        return self.post_unload_admission

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

    def loaded_model_inventory(self, **_kwargs) -> dict:
        state = "complete" if self.inventory_complete else "unknown"
        return {
            "complete": self.inventory_complete,
            "models": list(self.loaded),
            "errors": {} if self.inventory_complete else {"endpoint": "unknown"},
            "backends": {"ollama": {"complete": self.inventory_complete, "endpoints": {"http://fake": state}}},
        }

    def unload_inventory_model(self, row: dict, **_kwargs) -> bool:
        self.events.append(("unload_inventory_model", row.get("backend"), row.get("endpoint_url"), row.get("name")))
        self.loaded = [item for item in self.loaded if item is not row]
        return True

    def unload_configured_models(self, **_kwargs) -> dict:
        self.events.append(("unload_configured_models", _kwargs.get("include_llama", True)))
        requested = [str(row.get("name", "")) for row in self.loaded]
        remaining = [] if self.inventory_complete else None
        self.loaded = []
        return {
            "success": self.inventory_complete,
            "backend_available": True,
            "requested": requested,
            "unloaded": requested if self.inventory_complete else [],
            "remaining": remaining,
            "requested_by_backend": {"ollama": remaining},
            "remaining_by_backend": {"ollama": remaining},
            "backend_inventory_status": {"ollama": {"ollama": "complete" if self.inventory_complete else "unknown"}},
            "failed": {},
            "verified": self.inventory_complete,
            "complete": self.inventory_complete,
            "physical_vram_reclaimed": False,
        }

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


def test_handoff_refuses_incomplete_peer_inventory(tmp_path: Path):
    from local_ai_hub.tiered_ollama import TieredOllamaRuntime

    fast = FakeRuntime([{"name": "qwen2.5-coder:7b"}], inventory_complete=False)
    smart = FakeRuntime()
    runtime = TieredOllamaRuntime(_config(tmp_path), fast_runtime=fast, smart_runtime=smart)

    result = runtime.request("/api/generate", {"model": "qwen3.5:9b"})

    assert "inventory incomplete" in result["error"]
    assert smart.events == []


def test_handoff_unloads_exact_inventory_owner_and_endpoint(tmp_path: Path):
    from local_ai_hub.tiered_ollama import TieredOllamaRuntime

    row = {"name": "qwen2.5-coder:7b", "backend": "llama.cpp-sycl", "endpoint_url": "http://llama-a"}
    fast = FakeRuntime([row])
    smart = FakeRuntime()
    runtime = TieredOllamaRuntime(_config(tmp_path), fast_runtime=fast, smart_runtime=smart)

    runtime.request("/api/generate", {"model": "qwen3.5:9b"})

    assert fast.events == [("unload_inventory_model", "llama.cpp-sycl", "http://llama-a", "qwen2.5-coder:7b")]


def test_handoff_preserves_duplicate_model_identity_across_endpoints(tmp_path: Path):
    from local_ai_hub.tiered_ollama import TieredOllamaRuntime

    rows = [
        {"name": "qwen2.5-coder:7b", "backend": "llama.cpp-sycl", "endpoint_url": "http://llama-a"},
        {"name": "qwen2.5-coder:7b", "backend": "llama.cpp-sycl", "endpoint_url": "http://llama-b"},
    ]
    fast = FakeRuntime(rows)
    smart = FakeRuntime()
    runtime = TieredOllamaRuntime(_config(tmp_path), fast_runtime=fast, smart_runtime=smart)

    runtime.request("/api/generate", {"model": "qwen3.5:9b"})

    assert fast.events == [
        ("unload_inventory_model", "llama.cpp-sycl", "http://llama-a", "qwen2.5-coder:7b"),
        ("unload_inventory_model", "llama.cpp-sycl", "http://llama-b", "qwen2.5-coder:7b"),
    ]


def test_tiered_inventory_reports_each_tier_endpoint_and_completeness(tmp_path: Path):
    from local_ai_hub.tiered_ollama import TieredOllamaRuntime

    fast = FakeRuntime([{"name": "qwen2.5-coder:7b", "backend": "ollama", "endpoint_id": "http://fast"}])
    smart = FakeRuntime([{"name": "qwen3.5:9b", "backend": "ollama", "endpoint_id": "http://smart"}], inventory_complete=False)
    runtime = TieredOllamaRuntime(_config(tmp_path), fast_runtime=fast, smart_runtime=smart)

    inventory = runtime.loaded_model_inventory(force_refresh=True)

    assert inventory["complete"] is False
    assert inventory["endpoints"] == {
        "fast:ollama:http://fake": "complete",
        "smart:ollama:http://fake": "unknown",
    }
    assert [row["tier"] for row in inventory["models"]] == ["fast", "smart"]


def test_gaming_unload_returns_tiered_receipts_without_vram_claim(tmp_path: Path):
    from local_ai_hub.tiered_ollama import TieredOllamaRuntime

    fast = FakeRuntime([{"name": "qwen2.5-coder:7b"}])
    smart = FakeRuntime([{"name": "qwen3.5:9b"}])
    runtime = TieredOllamaRuntime(_config(tmp_path), fast_runtime=fast, smart_runtime=smart)

    result = runtime.unload_configured_models(timeout_seconds=1.0)

    assert result["complete"] is True
    assert result["verified"] is True
    assert result["remaining"] == []
    assert set(result["by_runtime"]) == {"fast", "smart"}
    assert result["physical_vram_reclaimed"] is False
    assert fast.events == [("unload_configured_models", True)]
    assert smart.events == [("unload_configured_models", False)]


def test_gaming_unload_keeps_incomplete_endpoint_unverified(tmp_path: Path):
    from local_ai_hub.tiered_ollama import TieredOllamaRuntime

    fast = FakeRuntime()
    smart = FakeRuntime(inventory_complete=False)
    runtime = TieredOllamaRuntime(_config(tmp_path), fast_runtime=fast, smart_runtime=smart)

    result = runtime.unload_configured_models(timeout_seconds=1.0)

    assert result["success"] is False
    assert result["complete"] is False
    assert result["verified"] is False
    assert result["remaining"] is None
    assert result["by_runtime"]["smart"]["backend_inventory_status"]["ollama"]["ollama"] == "unknown"


def test_post_unload_admission_capability_delegates_to_selected_runtime(tmp_path: Path):
    from local_ai_hub.tiered_ollama import TieredOllamaRuntime

    fast = FakeRuntime(post_unload_admission=False)
    smart = FakeRuntime(post_unload_admission=True)
    runtime = TieredOllamaRuntime(_config(tmp_path), fast_runtime=fast, smart_runtime=smart)

    assert runtime.supports_post_unload_admission("qwen3.5:9b") is True
    assert fast.events == []
    assert smart.events == [("supports_post_unload_admission", "qwen3.5:9b")]


def test_model_prepare_forwards_cancellation_controls_to_selected_runtime(tmp_path: Path):
    from local_ai_hub.tiered_ollama import TieredOllamaRuntime

    fast = FakeRuntime()
    smart = FakeRuntime()
    runtime = TieredOllamaRuntime(_config(tmp_path), fast_runtime=fast, smart_runtime=smart)
    should_stop = lambda: False
    admission = lambda: True
    deadline = time.monotonic() + 10.0

    runtime.prepare_model(
        "qwen2.5-coder:7b", should_stop=should_stop, deadline=deadline,
        post_unload_admission=admission,
    )

    assert fast.prepare_controls == [(should_stop, deadline, admission)]
    assert smart.prepare_controls == []


def test_cancel_during_inventory_does_not_unload_peer_or_start_target(tmp_path: Path):
    from local_ai_hub.tiered_ollama import TieredOllamaRuntime

    cancelled = threading.Event()
    fast = FakeRuntime([{"name": "qwen2.5-coder:7b"}])
    smart = FakeRuntime()
    original_inventory = fast.loaded_model_inventory
    def inventory(**kwargs):
        snapshot = original_inventory(**kwargs)
        cancelled.set()
        return snapshot
    fast.loaded_model_inventory = inventory
    runtime = TieredOllamaRuntime(_config(tmp_path), fast_runtime=fast, smart_runtime=smart)
    result = runtime.request_interruptible(
        "/api/generate", {"model": "qwen3.5:9b"}, cancelled.is_set,
        timeout=2.0, deadline=time.monotonic() + 2.0,
    )
    assert result.get("preempted") is True
    assert fast.loaded == [{"name": "qwen2.5-coder:7b"}]
    assert not fast.events and not smart.events


def test_cancel_during_prepare_inventory_does_not_unload_peer(tmp_path: Path):
    import pytest
    from local_ai_hub.ollama import ModelPreparationCancelled
    from local_ai_hub.tiered_ollama import TieredOllamaRuntime
    cancelled = threading.Event()
    fast = FakeRuntime([{"name": "qwen2.5-coder:7b"}])
    smart = FakeRuntime()
    original_inventory = fast.loaded_model_inventory
    def inventory(**kwargs):
        snapshot = original_inventory(**kwargs)
        cancelled.set()
        return snapshot
    fast.loaded_model_inventory = inventory
    runtime = TieredOllamaRuntime(_config(tmp_path), fast_runtime=fast, smart_runtime=smart)
    with pytest.raises(ModelPreparationCancelled):
        runtime.prepare_model("qwen3.5:9b", should_stop=cancelled.is_set, deadline=time.monotonic() + 2)
    assert fast.loaded == [{"name": "qwen2.5-coder:7b"}]
    assert not fast.events and not smart.events


def test_interruptible_request_forwards_deadline_to_selected_runtime(tmp_path: Path):
    from local_ai_hub.tiered_ollama import TieredOllamaRuntime

    fast = FakeRuntime()
    smart = FakeRuntime()
    runtime = TieredOllamaRuntime(_config(tmp_path), fast_runtime=fast, smart_runtime=smart)
    should_stop = lambda: False
    deadline = time.monotonic() + 5.0

    result = runtime.request_interruptible(
        "/api/generate", {"model": "qwen2.5-coder:7b"}, should_stop,
        timeout=0.5, deadline=deadline,
    )

    assert result["done"] is True
    assert len(fast.request_controls) == 1
    forwarded_stop, forwarded_timeout, forwarded_deadline = fast.request_controls[0]
    assert forwarded_stop is should_stop
    assert 0 < forwarded_timeout <= 0.5
    assert forwarded_deadline == deadline
    assert smart.request_controls == []


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
    assert smart.events == []


def test_unload_managed_models_reports_only_verified_unload(tmp_path: Path):
    from local_ai_hub.tiered_ollama import TieredOllamaRuntime

    smart = FakeRuntime([{"name": "qwen3.5:9b"}])
    runtime = TieredOllamaRuntime(_config(tmp_path), fast_runtime=FakeRuntime(), smart_runtime=smart)

    result = runtime.unload_managed_models(timeout_seconds=0.2)

    assert result["success"] is True
    assert result["unloaded"] == ["qwen3.5:9b"]
    assert result["remaining"] == []
    assert smart.events == [("unload_model", "qwen3.5:9b")]


def test_unload_managed_models_reports_runtime_failure(tmp_path: Path, monkeypatch):
    from local_ai_hub.tiered_ollama import TieredOllamaRuntime

    smart = FakeRuntime([{"name": "qwen3.5:9b"}])
    monkeypatch.setattr(smart, "unload_model", lambda _model: False)
    runtime = TieredOllamaRuntime(_config(tmp_path), fast_runtime=FakeRuntime(), smart_runtime=smart)

    result = runtime.unload_managed_models(timeout_seconds=0.2)

    assert result["success"] is False
    assert result["unloaded"] == []
    assert "cannot unload" in result["error"]


def test_unload_managed_models_times_out_if_runtime_keeps_model_loaded(tmp_path: Path, monkeypatch):
    from local_ai_hub.tiered_ollama import TieredOllamaRuntime

    smart = FakeRuntime([{"name": "qwen3.5:9b"}])
    monkeypatch.setattr(smart, "unload_model", lambda _model: True)
    runtime = TieredOllamaRuntime(_config(tmp_path), fast_runtime=FakeRuntime(), smart_runtime=smart)

    result = runtime.unload_managed_models(timeout_seconds=0.1)

    assert result["success"] is False
    assert result["remaining"] == ["qwen3.5:9b"]
    assert "deadline" in result["error"]


def test_unload_managed_models_does_not_claim_success_when_runtime_offline(tmp_path: Path):
    from local_ai_hub.tiered_ollama import TieredOllamaRuntime

    smart = FakeRuntime([{"name": "qwen3.5:9b"}])
    smart.online = False
    runtime = TieredOllamaRuntime(_config(tmp_path), fast_runtime=FakeRuntime(), smart_runtime=smart)

    result = runtime.unload_managed_models(timeout_seconds=0.2)

    assert result["success"] is False
    assert "unavailable" in result["error"]
    assert smart.events == []


def test_unload_managed_models_does_not_trust_empty_cache_when_status_fails(tmp_path: Path, monkeypatch):
    from local_ai_hub.tiered_ollama import TieredOllamaRuntime

    smart = FakeRuntime([{"name": "qwen3.5:9b"}])
    monkeypatch.setattr(smart, "unload_model", lambda _model: True)
    statuses = iter(({"models": [{"name": "qwen3.5:9b"}]}, {"error": "status unavailable"}))
    monkeypatch.setattr(smart, "request", lambda *_args, **_kwargs: next(statuses))
    runtime = TieredOllamaRuntime(_config(tmp_path), fast_runtime=FakeRuntime(), smart_runtime=smart)

    result = runtime.unload_managed_models(timeout_seconds=0.2)

    assert result["success"] is False
    assert "status unavailable" in result["error"]
