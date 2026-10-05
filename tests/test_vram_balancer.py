from __future__ import annotations

import threading
from unittest.mock import patch
import pytest
from local_ai_hub.vram_balancer import VRAMBalancer


def test_vram_balancer_nominal_pressure():
    balancer = VRAMBalancer({"models": {"fast_code": "qwen2.5-coder:7b", "draft_code": "qwen2.5-coder:3b-instruct-q5_K_M"}})
    mock_gpu = {
        "available": True,
        "vendor": "nvidia",
        "gpu_name": "NVIDIA GeForce RTX 4090",
        "vram_total_mb": 24576.0,
        "vram_used_mb": 6144.0,
        "vram_used_pct": 25.0,
    }
    with patch("local_ai_hub.vram_balancer.get_gpu_telemetry", return_value=mock_gpu):
        st = balancer.status()
        assert st["pressure_level"] == "nominal"
        assert st["context_budget_factor"] == 1.0
        assert st["throttle_background"] is False
        assert st["dynamic_context_tokens"] >= 32768
        assert st["speculative_inference"]["draft_model"] == "qwen2.5-coder:3b-instruct-q5_K_M"
        assert st["speculative_inference"]["strategy"] == "full_capacity"


def test_sample_vram_forces_fresh_snapshot():
    balancer = VRAMBalancer()
    first = {"available": True, "gpu_name": "GPU", "vram_total_mb": 1000.0, "vram_used_mb": 100.0}
    second = {"available": True, "gpu_name": "GPU", "vram_total_mb": 1000.0, "vram_used_mb": 250.0}
    with patch("local_ai_hub.vram_balancer.get_gpu_telemetry", side_effect=[first, second]):
        balancer.status()
        snapshot = balancer.sample_vram()

    assert snapshot["vram_used_mb"] == 250.0


def test_status_does_not_hold_balancer_lock_during_gpu_probe():
    balancer = VRAMBalancer()
    probe_entered = threading.Event()
    release_probe = threading.Event()
    pin_started = threading.Event()
    pin_finished = threading.Event()

    def slow_gpu_probe():
        probe_entered.set()
        release_probe.wait(timeout=3.0)
        return {"available": False}

    def pin_model():
        pin_started.set()
        balancer.pin_model("qwen2.5-coder:3b", ttl_seconds=10.0)
        pin_finished.set()

    with patch("local_ai_hub.vram_balancer.get_gpu_telemetry", side_effect=slow_gpu_probe):
        status_thread = threading.Thread(target=balancer.status)
        status_thread.start()
        pin_thread = None
        try:
            assert probe_entered.wait(timeout=1.0)
            pin_thread = threading.Thread(target=pin_model)
            pin_thread.start()
            assert pin_started.wait(timeout=1.0)
            assert pin_finished.wait(timeout=1.0), "GPU probe held the balancer lock"
        finally:
            release_probe.set()
            status_thread.join(timeout=2.0)
            if pin_thread is not None:
                pin_thread.join(timeout=2.0)

    assert not status_thread.is_alive()
    assert pin_thread is not None and not pin_thread.is_alive()
    assert balancer.get_pinned_model() == "qwen2.5-coder:3b"


def test_concurrent_forced_status_coalesces_probe_and_preserves_pin_update():
    balancer = VRAMBalancer()
    first_probe_entered = threading.Event()
    second_probe_entered = threading.Event()
    second_status_started = threading.Event()
    release_probe = threading.Event()
    probe_count = 0
    probe_count_lock = threading.Lock()
    results = []
    errors = []

    def slow_gpu_probe():
        nonlocal probe_count
        with probe_count_lock:
            probe_count += 1
            if probe_count == 1:
                first_probe_entered.set()
            else:
                second_probe_entered.set()
        release_probe.wait(timeout=3.0)
        return {"available": False}

    def sample(started=None):
        if started is not None:
            started.set()
        try:
            results.append(balancer.status(force=True))
        except BaseException as exc:
            errors.append(exc)

    with patch("local_ai_hub.vram_balancer.get_gpu_telemetry", side_effect=slow_gpu_probe):
        first = threading.Thread(target=sample)
        first.start()
        second = None
        try:
            assert first_probe_entered.wait(timeout=1.0)
            balancer.pin_model("qwen2.5-coder:7b", ttl_seconds=20.0)
            second = threading.Thread(target=sample, args=(second_status_started,))
            second.start()
            assert second_status_started.wait(timeout=1.0)
            assert not second_probe_entered.wait(timeout=0.1), "concurrent status launched another GPU probe"
        finally:
            release_probe.set()
            first.join(timeout=2.0)
            if second is not None:
                second.join(timeout=2.0)

    assert not first.is_alive()
    assert second is not None and not second.is_alive()
    assert errors == []
    assert probe_count == 1
    assert len(results) == 2
    assert all(row["pinned_model"]["model"] == "qwen2.5-coder:7b" for row in results)


def test_waiting_status_does_not_reuse_snapshot_invalidated_after_publish():
    balancer = VRAMBalancer()
    first_probe_entered = threading.Event()
    release_probe = threading.Event()
    waiter_is_blocked = threading.Event()
    snapshot_published = threading.Event()
    allow_sampler_return = threading.Event()
    probe_count = 0
    probe_count_lock = threading.Lock()
    results = {}
    errors = {}

    class ObservedCondition(threading.Condition):
        def wait(self, timeout=None):
            if threading.current_thread().name == "waiting-status":
                waiter_is_blocked.set()
            return super().wait(timeout)

    balancer._condition = ObservedCondition(balancer._lock)
    original_status_builder = balancer._status_from_telemetry

    def pause_after_publish(gpu):
        snapshot = original_status_builder(gpu)
        snapshot_published.set()
        allow_sampler_return.wait(timeout=3.0)
        return snapshot

    def slow_gpu_probe():
        nonlocal probe_count
        with probe_count_lock:
            probe_count += 1
        first_probe_entered.set()
        release_probe.wait(timeout=3.0)
        return {"available": False}

    def sample(label):
        try:
            results[label] = balancer.status(force=True)
        except BaseException as exc:
            errors[label] = exc

    with (
        patch("local_ai_hub.vram_balancer.get_gpu_telemetry", side_effect=slow_gpu_probe),
        patch.object(balancer, "_status_from_telemetry", side_effect=pause_after_publish),
    ):
        first = threading.Thread(target=sample, args=("first",), name="first-status")
        first.start()
        waiter = None
        try:
            assert first_probe_entered.wait(timeout=1.0)
            waiter = threading.Thread(target=sample, args=("waiter",), name="waiting-status")
            waiter.start()
            assert waiter_is_blocked.wait(timeout=1.0)
            release_probe.set()
            assert snapshot_published.wait(timeout=1.0)
            balancer.pin_model("qwen2.5-coder:9b", ttl_seconds=20.0)
        finally:
            release_probe.set()
            allow_sampler_return.set()
            first.join(timeout=2.0)
            if waiter is not None:
                waiter.join(timeout=2.0)

    assert not first.is_alive()
    assert waiter is not None and not waiter.is_alive()
    assert errors == {}
    assert probe_count == 2
    assert results["waiter"]["pinned_model"]["model"] == "qwen2.5-coder:9b"


def test_vram_balancer_high_pressure_downscale():
    balancer = VRAMBalancer({"models": {"fast_code": "qwen2.5-coder:7b"}})
    mock_gpu = {
        "available": True,
        "vendor": "nvidia",
        "gpu_name": "NVIDIA GeForce RTX 3080",
        "vram_total_mb": 10240.0,
        "vram_used_mb": 9000.0,
        "vram_used_pct": 87.8,
    }
    with patch("local_ai_hub.vram_balancer.get_gpu_telemetry", return_value=mock_gpu):
        st = balancer.status()
        assert st["pressure_level"] == "high"
        assert st["context_budget_factor"] == 0.5
        assert st["throttle_background"] is True
        assert balancer.should_throttle_background() is True
        assert balancer.recommended_context_budget(32768) == 16384


def test_vram_balancer_critical_pressure():
    balancer = VRAMBalancer({"models": {"fast_code": "qwen2.5-coder:7b"}})
    mock_gpu = {
        "available": True,
        "vendor": "nvidia",
        "gpu_name": "NVIDIA GeForce RTX 3060",
        "vram_total_mb": 12288.0,
        "vram_used_mb": 11800.0,
        "vram_used_pct": 96.0,
    }
    with patch("local_ai_hub.vram_balancer.get_gpu_telemetry", return_value=mock_gpu):
        st = balancer.status()
        assert st["pressure_level"] == "critical"
        assert st["context_budget_factor"] == 0.25
        assert st["throttle_background"] is True
        assert balancer.recommended_context_budget(32768) == 8192
        assert "throttled" in st["speculative_inference"]["strategy"]


def test_status_wait_timeout_returns_conservative_unavailable_without_second_sampler():
    balancer = VRAMBalancer()
    balancer._sample_wait_timeout_seconds = 0.01
    sampling_started = threading.Event()
    release_sampler = threading.Event()
    results = {}

    def blocked_sampler():
        sampling_started.set()
        assert release_sampler.wait(timeout=2.0)
        return {"available": True, "vendor": "nvidia", "gpu_name": "test", "vram_total_mb": 8192.0, "vram_used_mb": 1024.0}

    with patch("local_ai_hub.vram_balancer.get_gpu_telemetry", side_effect=blocked_sampler) as telemetry:
        sampler = threading.Thread(target=lambda: results.setdefault("sampler", balancer.status(force=True)))
        sampler.start()
        try:
            assert sampling_started.wait(timeout=1.0)

            fallback = balancer.status(force=True)

            assert fallback["available"] is False
            assert fallback["pressure_level"] == "unknown"
            assert fallback["context_budget_factor"] == 0.25
            assert fallback["throttle_background"] is True
            assert fallback["telemetry_stale"] is True
            assert fallback["telemetry_wait_timed_out"] is True
            assert telemetry.call_count == 1
        finally:
            release_sampler.set()
            sampler.join(timeout=1.0)

        assert not sampler.is_alive()


def test_status_wait_timeout_returns_conservative_stale_cache():
    balancer = VRAMBalancer()
    cached_gpu = {
        "available": True,
        "vendor": "nvidia",
        "gpu_name": "test",
        "vram_total_mb": 8192.0,
        "vram_used_mb": 1024.0,
        "vram_used_pct": 12.5,
    }
    with patch("local_ai_hub.vram_balancer.get_gpu_telemetry", return_value=cached_gpu):
        cached = balancer.status()

    balancer._sample_wait_timeout_seconds = 0.01
    sampling_started = threading.Event()
    release_sampler = threading.Event()
    results = {}

    def blocked_sampler():
        sampling_started.set()
        assert release_sampler.wait(timeout=2.0)
        return cached_gpu

    with patch("local_ai_hub.vram_balancer.get_gpu_telemetry", side_effect=blocked_sampler) as telemetry:
        sampler = threading.Thread(target=lambda: results.setdefault("sampler", balancer.status(force=True)))
        sampler.start()
        try:
            assert sampling_started.wait(timeout=1.0)

            fallback = balancer.status(force=True)

            assert fallback["telemetry_wait_timed_out"] is True
            assert fallback["available"] is False
            assert fallback["pressure_level"] == "unknown"
            assert fallback["context_budget_factor"] == 0.25
            assert fallback["throttle_background"] is True
            assert fallback["telemetry_stale"] is True
            assert fallback["gpu_name"] == cached["gpu_name"]
            assert fallback["dynamic_context_tokens"] <= cached["dynamic_context_tokens"] * 0.25
            assert cached["available"] is True
            assert telemetry.call_count == 1
        finally:
            release_sampler.set()
            sampler.join(timeout=1.0)

        assert not sampler.is_alive()
