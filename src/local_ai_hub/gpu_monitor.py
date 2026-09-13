from __future__ import annotations

import os
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


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).strip().replace("W", "").replace("%", "").replace("C", ""))
    except (TypeError, ValueError):
        return default


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
        cmd = ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_VideoController | Where-Object { $_.AdapterRAM -gt 0 } | Select-Object -First 1 Name, AdapterRAM | ConvertTo-Json"]
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=2.5, check=False, **hidden_run_kwargs())
        if completed.returncode == 0 and completed.stdout.strip():
            import json
            data = json.loads(completed.stdout)
            name = str(data.get("Name", "Windows GPU"))
            raw_ram = float(data.get("AdapterRAM", 0))
            total_mb = round(raw_ram / (1024 * 1024), 1)
            vendor = "amd" if "amd" in name.lower() or "radeon" in name.lower() else "intel" if "intel" in name.lower() else "nvidia" if "nvidia" in name.lower() else "generic"
            backend = "directml" if vendor in {"amd", "intel"} else "cuda" if vendor == "nvidia" else "directx"
            from .hardware import _is_integrated_gpu
            is_integrated = _is_integrated_gpu(vendor, name, int(total_mb))
            return {
                "available": True, "vendor": vendor, "backend": backend, "gpu_name": name,
                "gpu_utilization_pct": 0.0, "vram_used_mb": 0.0,
                "vram_total_mb": 0.0 if is_integrated else total_mb,
                "reported_adapter_memory_mb": total_mb if is_integrated else 0.0,
                "integrated": is_integrated, "shared_memory": is_integrated,
                "vram_used_pct": 0.0, "live_metrics": True, "timestamp": time.time(),
            }
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
    return {
        "cpu_count": int(cpu_info.get("logical_cores", os.cpu_count() or 1)),
        "cpu": cpu_info, "platform": hw.get("platform"), "arch": hw.get("arch"), "profile": hw.get("profile"),
        "ram": {"total_gb": total_gb, "available_gb": available_gb, "used_gb": round(used_gb, 1), "used_pct": round(100.0 * used_gb / max(0.1, total_gb), 1)},
        "gpu": get_gpu_telemetry(), "gpus": hw.get("gpus") or [],
        "npus": hw.get("npus") or [], "openvino_devices": hw.get("openvino_devices") or [],
    }
