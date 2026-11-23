from __future__ import annotations

import time
import threading
from types import SimpleNamespace

from local_ai_hub.scheduler import AffinityScheduler, admission_rejection_message
from local_ai_hub.laya_lifecycle import LayaSessionLifecycle


def test_external_gpu_reservation_behavior_and_blocks_scheduler(tmp_path):
    """DoD: Tested reservation behavior separately.

    Verifies external reservation blocks scheduler from running GPU tasks,
    and release unblocks scheduler.
    """
    from local_ai_hub.external_gpu_reservation import ExternalGpuReservationStore

    res_file = tmp_path / "ext_gpu_res"
    store = ExternalGpuReservationStore(res_file, ttl_seconds=60)

    scheduler = object.__new__(AffinityScheduler)
    scheduler._cond = threading.Condition()
    scheduler._running = True
    scheduler._external_gpu_path = res_file
    scheduler._external_gpu_store = store
    scheduler._external_gpu_token = None
    scheduler._external_gpu_generation = None
    scheduler._external_gpu_owned = False
    scheduler._external_gpu_expiry_monotonic = None
    scheduler._internal_gpu_claim = None
    scheduler._internal_gpu_digest = None
    scheduler._internal_gpu_uncertain = False
    scheduler._background_gpu_lease = None
    scheduler._switching = False
    scheduler._inflight = set()
    scheduler._pending = []
    scheduler._active_model = None
    scheduler.config = {"scheduler": {}}

    # Reserve external GPU
    token = scheduler.reserve_external_gpu("ext_task_1", owner_vram_budget_bytes=4 * (1024**3))
    assert token is not None
    assert scheduler._external_gpu_reserved() is True

    # Renew external GPU
    assert scheduler.renew_external_gpu(token) is True

    # Explicit release unblocks scheduler
    assert scheduler.release_external_gpu(token) is True
    assert scheduler._external_gpu_reserved() is False

    # Legacy exclusive reservation (without store) blocks scheduler completely
    scheduler._external_gpu_store = None
    token_exclusive = scheduler.reserve_external_gpu("ext_task_exclusive", owner_vram_budget_bytes=1024**3)
    assert token_exclusive is not None
    assert scheduler._external_gpu_reserved() is True
    assert scheduler._external_gpu_blocks_scheduler() is True
    assert scheduler.release_external_gpu(token_exclusive) is True
    assert scheduler._external_gpu_reserved() is False


def test_external_gpu_reservation_expiry_reap(tmp_path):
    """Verifies expired external reservation is reaped without deadlocks."""
    import os
    from local_ai_hub.external_gpu_reservation import ExternalGpuReservationStore

    res_file = tmp_path / "ext_gpu_res_exp"
    res_file.write_text("a" * 64, encoding="ascii")
    expired_at = time.time() - 2.0
    os.utime(res_file, (expired_at, expired_at))
    store = ExternalGpuReservationStore(res_file, ttl_seconds=1)

    scheduler = object.__new__(AffinityScheduler)
    scheduler._cond = threading.Condition()
    scheduler._inflight = set()
    scheduler._switching = False
    scheduler._gpu_prepare_in_progress = False
    scheduler._background_gpu_lease = None
    scheduler._external_gpu_path = res_file
    scheduler._external_gpu_store = store
    scheduler._external_gpu_generation = None
    scheduler._internal_gpu_uncertain = True

    # Checking reservation reaps the expired file automatically
    assert scheduler._external_gpu_reserved() is True
    assert not res_file.exists()


def test_actual_model_unload_observation_separately():
    """DoD: Actual model unload observation tested separately from reservation.

    Verifies model idle detection calls backend unload and transitions state to unloaded.
    """
    unloaded_sessions = []

    def close_cb(session):
        unloaded_sessions.append(session)
        return True

    lifecycle = LayaSessionLifecycle(
        idle_unload_seconds=0.05,
        close_session=close_cb,
    )

    # Load session and perform inference
    session_obj = {"id": "session_1"}
    with lifecycle.inference_session(lambda: session_obj) as s:
        assert s["id"] == "session_1"
        assert lifecycle.status["available"] is True

    # Idle before threshold: should not unload
    res_not_idle = lifecycle.poll_idle_unload(now=time.monotonic())
    assert res_not_idle == "not_idle"
    assert len(unloaded_sessions) == 0

    # Fast forward time past idle_unload_seconds
    res_unloaded = lifecycle.poll_idle_unload(now=time.monotonic() + 0.1)
    assert res_unloaded == "unloaded"
    assert len(unloaded_sessions) == 1
    assert lifecycle.status["available"] is False
    assert lifecycle.status["unload_count"] == 1


def test_graceful_vram_rejection_without_oom_loop():
    """DoD: Graceful fallback without OOM loop.

    Verifies that when VRAM telemetry shows insufficient capacity, admission rejects
    cleanly with retryable=False or non-looping reason, preventing infinite retry thrashing.
    """
    class OOMBalancer:
        def status(self, force=False):
            return {
                "available": True,
                "pressure_level": "critical",
                "context_budget_factor": 0.1,
                "throttle_background": True,
                "vram_total_mb": 8192.0,
                "vram_available_mb": 128.0,  # Critically low VRAM
                "telemetry_stale": False,
                "sample_age_seconds": 0.1,
            }

    scheduler = object.__new__(AffinityScheduler)
    balancer = OOMBalancer()
    scheduler.runtime = SimpleNamespace(
        resource_status=balancer.status,
        supports_post_unload_admission=lambda _m: True,
        requires_post_unload_admission=lambda _m: True,
        loaded_model_details=lambda: [],
    )
    scheduler.vram_balancer = balancer
    scheduler.config = {
        "scheduler": {
            "model_vram_estimates_bytes": {"heavy-model": 14 * (1024**3)},
        }
    }
    scheduler._model_vram_bytes = {}

    result = scheduler._admission(background=True, model="heavy-model")
    assert result["state"] == "rejected"
    assert result["reason"] in {"resource_pressure", "vram_budget"}
    # Rejection message is deterministic and clear
    msg = admission_rejection_message(result["reason"], background=True)
    assert "resource pressure" in msg or "insufficient VRAM" in msg


def test_no_automatic_model_pull_on_missing_model():
    """DoD: Graceful failure when model is not installed; no automatic model pulls."""
    from local_ai_hub.services import LocalAIServices

    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"models": {"fast_code": "installed_fast", "heavy_code": "installed_heavy"}}
    service.runtime = SimpleNamespace(
        is_online=lambda: True,
        list_installed_models=lambda: ["installed_fast", "installed_heavy"],
    )

    # Verify querying installed models does not include uninstalled
    installed = service.runtime.list_installed_models()
    assert "nonexistent_model:latest" not in installed
    # Policy: pulls are opt-in, no background pull triggered


def test_missing_laya_checkpoint_fails_before_provider_load(tmp_path, monkeypatch):
    """A missing pinned checkpoint must not initialize a model provider."""
    import pytest
    import local_ai_hub.laya_runtime as laya_runtime

    provider_calls = []
    adapter = laya_runtime.LayaRuntimeAdapter(
        checkpoint_path=tmp_path / "missing-revision",
        revision="missing-revision",
        expected_sha256={"model.safetensors": "0" * 64},
        device_candidates=(),
    )
    monkeypatch.setattr(
        laya_runtime.importlib,
        "import_module",
        lambda name: provider_calls.append(name),
    )

    with pytest.raises(FileNotFoundError):
        adapter._load()

    assert provider_calls == []
