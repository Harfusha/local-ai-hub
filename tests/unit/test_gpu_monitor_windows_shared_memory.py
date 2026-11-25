from __future__ import annotations

import ctypes
import time
from types import SimpleNamespace

from local_ai_hub import gpu_monitor
from local_ai_hub.vram_balancer import VRAMBalancer


def test_windows_shared_memory_metrics_reads_physical_available_memory(monkeypatch) -> None:
    mib = 1024 * 1024

    class _GlobalMemoryStatusEx:
        def __call__(self, pointer):
            status = pointer._obj
            status.ullTotalPhys = 32 * 1024 * mib
            status.ullAvailPhys = 12 * 1024 * mib
            return 1

    api = _GlobalMemoryStatusEx()
    monkeypatch.setattr(gpu_monitor.os, "name", "nt")
    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        lambda *_args, **_kwargs: SimpleNamespace(GlobalMemoryStatusEx=api),
        raising=False,
    )

    sample = gpu_monitor._windows_shared_memory_metrics()

    assert sample == {
        "unified_memory_mb": 32768.0,
        "unified_memory_used_mb": 20480.0,
        "unified_memory_available_mb": 12288.0,
        "unified_memory_used_pct": 62.5,
    }


def test_integrated_windows_gpu_uses_fresh_shared_memory_telemetry(monkeypatch) -> None:
    monkeypatch.setattr(gpu_monitor.os, "name", "nt")
    monkeypatch.setattr(
        gpu_monitor,
        "_windows_sample",
        lambda: {"adapters": [{"Name": "Intel(R) Arc(TM) Graphics", "AdapterRAM": 0}]},
    )
    monkeypatch.setattr(
        gpu_monitor,
        "_windows_shared_memory_metrics",
        lambda: {
            "unified_memory_mb": 32768.0,
            "unified_memory_used_mb": 8192.0,
            "unified_memory_available_mb": 24576.0,
            "unified_memory_used_pct": 25.0,
        },
    )

    sample = gpu_monitor._windows_live()

    assert sample is not None
    assert sample["integrated"] is True
    assert sample["vram_total_mb"] == 0.0
    assert sample["unified_memory_available_mb"] == 24576.0
    assert time.time() - sample["timestamp"] < 1.0

    status = VRAMBalancer()._status_from_telemetry(sample)
    assert status["available"] is True
    assert status["telemetry_stale"] is False
    assert status["policy_measurement_basis"] == "shared_unified_observed"


def test_integrated_inventory_fallback_gets_fresh_shared_memory_sample(monkeypatch) -> None:
    monkeypatch.setattr(gpu_monitor.os, "name", "nt")
    monkeypatch.setattr(gpu_monitor, "_GPU_CACHE", {})
    monkeypatch.setattr(gpu_monitor, "_GPU_CACHE_TIME", 0.0)
    monkeypatch.setattr(gpu_monitor, "_nvidia_live", lambda: None)
    monkeypatch.setattr(gpu_monitor, "_rocm_live", lambda: None)
    monkeypatch.setattr(gpu_monitor, "_windows_live", lambda: None)
    monkeypatch.setattr(
        gpu_monitor,
        "detect_hardware",
        lambda **_kwargs: {
            "gpus": [{"vendor": "intel", "name": "Intel Arc", "integrated": True, "vram_mb": 0}]
        },
    )
    monkeypatch.setattr(
        gpu_monitor,
        "_windows_shared_memory_metrics",
        lambda: {
            "unified_memory_mb": 32768.0,
            "unified_memory_used_mb": 8192.0,
            "unified_memory_available_mb": 24576.0,
            "unified_memory_used_pct": 25.0,
        },
    )

    sample = gpu_monitor.get_gpu_telemetry()

    assert sample["integrated"] is True
    assert sample["vram_total_mb"] == 0
    assert sample["unified_memory_available_mb"] == 24576.0
    assert time.time() - sample["timestamp"] < 1.0
    status = VRAMBalancer()._status_from_telemetry(sample)
    assert status["available"] is True
    assert status["telemetry_stale"] is False


def test_balancer_uses_cached_integrated_inventory_for_fresh_windows_sample(monkeypatch) -> None:
    monkeypatch.setattr(gpu_monitor.os, "name", "nt")
    monkeypatch.setattr(
        gpu_monitor,
        "_windows_live",
        lambda: (_ for _ in ()).throw(AssertionError("slow Windows probe must be skipped")),
    )
    monkeypatch.setattr(
        gpu_monitor,
        "detect_hardware",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("hardware detection must be skipped")),
    )
    monkeypatch.setattr(
        gpu_monitor,
        "_windows_shared_memory_metrics",
        lambda: {
            "unified_memory_mb": 32768.0,
            "unified_memory_used_mb": 8192.0,
            "unified_memory_available_mb": 24576.0,
            "unified_memory_used_pct": 25.0,
        },
    )

    status = VRAMBalancer({
        "_hardware": {
            "gpus": [{"vendor": "intel", "name": "Intel Arc", "vram_mb": 0, "integrated": True}],
        },
    }).status(force=True)

    assert status["available"] is True
    assert status["telemetry_stale"] is False
    assert status["sample_age_seconds"] is not None
    assert status["policy_headroom_mb"] == 24576.0


def test_openvino_gpu_inventory_supplies_integrated_shared_memory(monkeypatch) -> None:
    monkeypatch.setattr(gpu_monitor.os, "name", "nt")
    monkeypatch.setattr(
        gpu_monitor,
        "_windows_shared_memory_metrics",
        lambda: {
            "unified_memory_mb": 32768.0,
            "unified_memory_used_mb": 8192.0,
            "unified_memory_available_mb": 24576.0,
            "unified_memory_used_pct": 25.0,
        },
    )
    intel_gpu = {
        "vendor": "intel",
        "device": "GPU",
        "kind": "gpu",
        "name": "Intel(R) Arc(TM) Graphics (iGPU)",
        "backend": "openvino",
        "runtime_available": True,
    }

    for hardware in (
        {"profile": "integrated", "gpus": [], "openvino_gpu_devices": [intel_gpu]},
        {"profile": "integrated", "gpus": [], "openvino_devices": [intel_gpu]},
    ):
        sample = gpu_monitor.get_gpu_telemetry_for_hardware(hardware)

        assert sample["available"] is True
        assert sample["integrated"] is True
        assert sample["unified_memory_available_mb"] == 24576.0
        assert sample["vram_available_mb"] is None
