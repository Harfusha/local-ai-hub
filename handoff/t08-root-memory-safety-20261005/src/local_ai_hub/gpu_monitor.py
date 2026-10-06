from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
from typing import Any

from .hardware import detect_hardware
from .process_utils import hidden_run_kwargs

_GPU_CACHE: dict[str, Any] = {}
_GPU_CACHE_TIME = 0.0
_GPU_LOCK = threading.Lock()
_WINDOWS_CACHE: dict[str, Any] = {}
_WINDOWS_CACHE_TIME = 0.0
_WINDOWS_LOCK = threading.Lock()
_WINDOWS_REFRESHING = False


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).strip().replace("W", "").replace("%", "").replace("C", ""))
    except (TypeError, ValueError):
        return default


def _bounded_percent(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
        if not math.isfinite(number):
            return None
        return round(min(100.0, max(0.0, number)), 1)
    except (TypeError, ValueError):
        return None


def _refresh_windows_sample() -> None:
    global _WINDOWS_CACHE, _WINDOWS_CACHE_TIME, _WINDOWS_REFRESHING
    sample: dict[str, Any] = {}
    script = (
        "$ErrorActionPreference = 'SilentlyContinue'; "
        "$adapters = @(Get-CimInstance -ClassName Win32_VideoController | Where-Object { $_.AdapterRAM -gt 0 } | Select-Object Name,AdapterRAM); "
        "$cpuValues = @(Get-CimInstance -ClassName Win32_Processor | ForEach-Object { $_.LoadPercentage } | Where-Object { $null -ne $_ }); "
        "$cpu = $null; if ($cpuValues.Count -gt 0) { $cpu = [math]::Round(($cpuValues | Measure-Object -Average).Average, 1) }; "
        "$engines = @(); try { $engines = @(Get-CimInstance -Namespace root/cimv2 -ClassName Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine -ErrorAction Stop | Select-Object Name,UtilizationPercentage) } catch {}; "
        "[pscustomobject]@{ adapters = $adapters; cpu_utilization_pct = $cpu; engines = $engines } | ConvertTo-Json -Compress -Depth 4"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=4.0, check=False,
            encoding="utf-8", errors="replace", **hidden_run_kwargs(),
        )
        if completed.returncode == 0 and completed.stdout.strip():
            parsed = json.loads(completed.stdout)
            if isinstance(parsed, dict):
                sample = parsed
    except Exception:
        pass
    with _WINDOWS_LOCK:
        _WINDOWS_CACHE, _WINDOWS_CACHE_TIME = sample, time.time()
        _WINDOWS_REFRESHING = False


def _windows_sample() -> dict[str, Any]:
    """Return cached Windows counters and refresh them off the request thread."""
    global _WINDOWS_REFRESHING
    if os.name != "nt" or not shutil.which("powershell"):
        return {}
    now = time.time()
    if _WINDOWS_CACHE_TIME and now - _WINDOWS_CACHE_TIME < 1.5:
        return dict(_WINDOWS_CACHE)
    with _WINDOWS_LOCK:
        now = time.time()
        if _WINDOWS_CACHE_TIME and now - _WINDOWS_CACHE_TIME < 1.5:
            return dict(_WINDOWS_CACHE)
        if _WINDOWS_REFRESHING:
            return dict(_WINDOWS_CACHE)
        try:
            _WINDOWS_REFRESHING = True
            threading.Thread(target=_refresh_windows_sample, daemon=True, name="windows-hardware-telemetry").start()
        except Exception:
            _WINDOWS_REFRESHING = False
    return dict(_WINDOWS_CACHE)


def _windows_engine_usage(engines: Any) -> dict[str, float | None]:
    """Return busiest GPU and neural engines from Windows per-process counters."""
    if isinstance(engines, dict):
        items = [engines]
    elif isinstance(engines, list):
        items = engines
    else:
        items = []
    totals: dict[tuple[str, str, str, str, str], float] = {}
    pattern = re.compile(r"_luid_(0x[0-9a-f]+)_(0x[0-9a-f]+)_phys_(\d+)_eng_(\d+)_engtype_(.*)$", re.IGNORECASE)
    for item in items:
        if not isinstance(item, dict):
            continue
        match = pattern.search(str(item.get("Name", "")))
        if not match:
            continue
        engine_type = match.group(5).strip().lower()
        if not engine_type:
            continue
        usage = _bounded_percent(item.get("UtilizationPercentage"))
        if usage is None:
            continue
        key = (match.group(1).lower(), match.group(2).lower(), match.group(3), match.group(4), engine_type)
        totals[key] = totals.get(key, 0.0) + usage
    gpu_engines = [min(100.0, value) for (*_, kind), value in totals.items() if "neural" not in kind and "npu" not in kind]
    npu_engines = [min(100.0, value) for (*_, kind), value in totals.items() if "neural" in kind or "npu" in kind]
    return {
        "gpu_utilization_pct": round(max(gpu_engines), 1) if gpu_engines else None,
        "npu_utilization_pct": round(max(npu_engines), 1) if npu_engines else None,
    }


def _nvidia_live() -> dict[str, Any] | None:
    smi = shutil.which("nvidia-smi")
    if not smi and os.name == "nt":
        candidate = r"C:\Windows\System32\nvidia-smi.exe"
        if os.path.exists(candidate):
            smi = candidate
    if not smi:
        return None
    try:
        completed = subprocess.run(
            [smi, "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw", "--format=csv,noheader,nounits"],
            stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=2.0, check=False, encoding="utf-8", errors="replace", **hidden_run_kwargs(),
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            return None
        parts = [p.strip() for p in completed.stdout.strip().splitlines()[0].split(",")]
        if len(parts) < 6:
            return None
        used_mb = _safe_float(parts[2])
        total_mb = _safe_float(parts[3])
        return {
            "available": True, "vendor": "nvidia", "backend": "cuda", "gpu_name": parts[0],
            "gpu_utilization_pct": _safe_float(parts[1]), "vram_used_mb": used_mb, "vram_total_mb": total_mb,
            "vram_used_pct": round(100.0 * used_mb / max(1.0, total_mb), 1), "temperature_c": _safe_float(parts[4]),
            "power_draw_w": _safe_float(parts[5]), "timestamp": time.time(),
        }
    except Exception:
        return None


def _rocm_live() -> dict[str, Any] | None:
    smi = shutil.which("rocm-smi")
    if not smi:
        return None
    try:
        import json
        completed = subprocess.run(
            [smi, "--showuse", "--showmeminfo", "vram", "--json"],
            stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=2.0, check=False, encoding="utf-8", errors="replace", **hidden_run_kwargs(),
        )
        if completed.returncode == 0 and completed.stdout.strip():
            data = json.loads(completed.stdout)
            if isinstance(data, dict):
                first_card = next(iter(data.values())) if data else {}
                used_bytes = _safe_float(first_card.get("VRAM Total Used Memory (B)", 0))
                total_bytes = _safe_float(first_card.get("VRAM Total Memory (B)", 0))
                used_mb = used_bytes / (1024 * 1024) if used_bytes else 0.0
                total_mb = total_bytes / (1024 * 1024) if total_bytes else 0.0
                use_pct = _safe_float(first_card.get("GPU use (%)", 0))
                return {
                    "available": True, "vendor": "amd", "backend": "rocm", "gpu_name": "AMD Radeon GPU",
                    "gpu_utilization_pct": use_pct, "vram_used_mb": round(used_mb, 1), "vram_total_mb": round(total_mb, 1),
                    "vram_used_pct": round(100.0 * used_mb / max(1.0, total_mb), 1) if total_mb else 0.0,
                    "live_metrics": True, "timestamp": time.time(),
                }
    except Exception:
        pass
    return None


def _windows_live() -> dict[str, Any] | None:
    if os.name != "nt":
        return None
    try:
        sample = _windows_sample()
        adapters = sample.get("adapters") or []
        if isinstance(adapters, dict):
            adapters = [adapters]
        if not adapters:
            return None
        data = adapters[0]
        name = str(data.get("Name", "Windows GPU"))
        raw_ram = float(data.get("AdapterRAM", 0))
        total_mb = round(raw_ram / (1024 * 1024), 1)
        vendor = "amd" if "amd" in name.lower() or "radeon" in name.lower() else "intel" if "intel" in name.lower() else "nvidia" if "nvidia" in name.lower() else "generic"
        backend = "directml" if vendor in {"amd", "intel"} else "cuda" if vendor == "nvidia" else "directx"
        from .hardware import _is_integrated_gpu
        is_integrated = _is_integrated_gpu(vendor, name, int(total_mb))
        engine_usage = _windows_engine_usage(sample.get("engines"))
        utilization = engine_usage["gpu_utilization_pct"] if len(adapters) == 1 else None
        result = {
            "available": True, "vendor": vendor, "backend": backend, "gpu_name": name,
            "vram_used_mb": 0.0,
            "vram_total_mb": 0.0 if is_integrated else total_mb,
            "reported_adapter_memory_mb": total_mb if is_integrated else 0.0,
            "integrated": is_integrated, "shared_memory": is_integrated,
            "vram_used_pct": 0.0, "live_metrics": utilization is not None, "timestamp": time.time(),
        }
        if utilization is not None:
            result["gpu_utilization_pct"] = utilization
        return result
    except Exception:
        pass
    return None


def get_gpu_telemetry() -> dict[str, Any]:
    """Return vendor-neutral GPU information and live metrics where available."""
    global _GPU_CACHE, _GPU_CACHE_TIME
    now = time.time()
    if _GPU_CACHE and now - _GPU_CACHE_TIME < 1.5:
        return dict(_GPU_CACHE)
    with _GPU_LOCK:
        now = time.time()
        if _GPU_CACHE and now - _GPU_CACHE_TIME < 1.5:
            return dict(_GPU_CACHE)
        live = _nvidia_live()
        if live is None:
            live = _rocm_live()
        if live is None:
            live = _windows_live()
        if live is not None:
            _GPU_CACHE, _GPU_CACHE_TIME = live, now
            return dict(live)
        hw = detect_hardware()
        gpus = hw.get("gpus", []) if isinstance(hw, dict) else []
        if not gpus:
            result = {"available": False, "reason": "no supported GPU telemetry provider detected"}
        else:
            gpu = dict(gpus[0])
            integrated = bool(gpu.get("integrated", False))
            reported_vram = int(gpu.get("vram_mb", 0) or 0)
            result = {
                "available": True, "vendor": gpu.get("vendor", "unknown"), "backend": gpu.get("backend", "unknown"),
                "gpu_name": gpu.get("name", "GPU"),
                # Windows AdapterRAM on an iGPU is aperture metadata, not a safe
                # dedicated-memory budget. Keep it diagnostic-only.
                "vram_total_mb": 0 if integrated else reported_vram,
                "reported_adapter_memory_mb": reported_vram if integrated else 0,
                "unified_memory_mb": int(gpu.get("unified_memory_mb", 0) or 0),
                "integrated": integrated, "shared_memory": bool(gpu.get("shared_memory", integrated)),
                "live_metrics": False,
            }
        _GPU_CACHE, _GPU_CACHE_TIME = result, now
        return dict(result)


def get_dynamic_token_budget(base_tokens: int = 32768, min_tokens: int = 8192, max_tokens: int = 65536) -> int:
    """Choose a conservative context ceiling from currently known graphics memory."""
    telemetry = get_gpu_telemetry()
    total_mb = float(telemetry.get("vram_total_mb", 0) or telemetry.get("unified_memory_mb", 0) or 0)
    used_mb = float(telemetry.get("vram_used_mb", 0) or 0)
    available_mb = max(0.0, total_mb - used_mb) if total_mb else 0.0
    if total_mb <= 0:
        profile = detect_hardware().get("profile", "balanced")
        return min(base_tokens, 12288) if profile == "integrated" else min(base_tokens, 16384) if profile in {"cpu", "low"} else base_tokens
    if available_mb >= 14000:
        return min(max_tokens, 65536)
    if available_mb >= 7000:
        return min(max_tokens, 49152)
    if available_mb >= 3500:
        return min(base_tokens, max_tokens)
    return max(min_tokens, min(base_tokens, 16384))


def get_system_telemetry() -> dict[str, Any]:
    hw = detect_hardware() or {}
    cpu_info = hw.get("cpu") or {}
    ram_info = hw.get("ram") or {}
    total_gb = float(ram_info.get("total_gb", 0.0) or 0.0)
    available_gb = float(ram_info.get("available_gb", 0.0) or 0.0)
    used_gb = max(0.0, total_gb - available_gb)
    gpu = get_gpu_telemetry()
    windows_sample = _windows_sample()
    engine_usage = _windows_engine_usage(windows_sample.get("engines"))
    adapters = windows_sample.get("adapters") or []
    if isinstance(adapters, dict):
        adapters = [adapters]
    from .hardware import _is_integrated_gpu
    integrated_adapters = [
        adapter for adapter in adapters
        if isinstance(adapter, dict)
        and _is_integrated_gpu(
            "intel" if "intel" in str(adapter.get("Name", "")).lower() else
            "amd" if "amd" in str(adapter.get("Name", "")).lower() or "radeon" in str(adapter.get("Name", "")).lower() else "generic",
            str(adapter.get("Name", "")),
            int(float(adapter.get("AdapterRAM", 0) or 0) / (1024 * 1024)),
        )
    ]
    hardware_gpus = hw.get("gpus") or []
    igpu_detected = bool(integrated_adapters) or bool(gpu.get("integrated")) or any(
        isinstance(item, dict) and item.get("integrated") for item in hardware_gpus
    )
    igpu_utilization = None
    if len(adapters) == 1 and integrated_adapters:
        igpu_utilization = engine_usage["gpu_utilization_pct"]
    elif not adapters and gpu.get("integrated"):
        igpu_utilization = gpu.get("gpu_utilization_pct")
    cpu_utilization = _bounded_percent(windows_sample.get("cpu_utilization_pct"))
    npus = hw.get("npus") or []
    npu_utilization = engine_usage["npu_utilization_pct"]
    return {
        "cpu_count": int(cpu_info.get("logical_cores", os.cpu_count() or 1)),
        "cpu_utilization_pct": cpu_utilization,
        "cpu": cpu_info, "platform": hw.get("platform"), "arch": hw.get("arch"), "profile": hw.get("profile"),
        "ram": {"total_gb": total_gb, "available_gb": available_gb, "used_gb": round(used_gb, 1), "used_pct": round(100.0 * used_gb / max(0.1, total_gb), 1)},
        "gpu": gpu, "gpus": hardware_gpus,
        "igpu_available": igpu_detected, "igpu_utilization_pct": _bounded_percent(igpu_utilization),
        "npu_available": bool(npus) or engine_usage["npu_utilization_pct"] is not None,
        "npu_utilization_pct": _bounded_percent(npu_utilization),
        "npus": npus, "openvino_devices": hw.get("openvino_devices") or [],
    }
