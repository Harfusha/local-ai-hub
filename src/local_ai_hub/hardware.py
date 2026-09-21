from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
from functools import lru_cache
from typing import Any

from .process_utils import hidden_run_kwargs


def _run(cmd: list[str], timeout: float = 2.5) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, check=False,
            encoding="utf-8", errors="replace", **hidden_run_kwargs(),
        )
    except Exception:
        return None


def _memory_bytes() -> tuple[int, int]:
    """Return total/available physical memory without mandatory dependencies."""
    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        try:
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):  # type: ignore[attr-defined]
                return int(stat.ullTotalPhys), int(stat.ullAvailPhys)
        except Exception:
            pass
    if sys_platform() == "darwin":
        cp = _run(["sysctl", "-n", "hw.memsize"])
        total = int(cp.stdout.strip()) if cp and cp.returncode == 0 and cp.stdout.strip().isdigit() else 0
        # vm_stat pages are normally 4096/16384 bytes. Parse the declared page size.
        vm = _run(["vm_stat"])
        if vm and vm.returncode == 0:
            try:
                lines = vm.stdout.splitlines()
                page_size = int(lines[0].split("page size of", 1)[1].split("bytes", 1)[0].strip())
                values: dict[str, int] = {}
                for line in lines[1:]:
                    if ":" not in line:
                        continue
                    key, value = line.split(":", 1)
                    values[key.strip()] = int(value.strip().rstrip("."))
                avail_pages = values.get("Pages free", 0) + values.get("Pages inactive", 0) + values.get("Pages speculative", 0)
                return total, avail_pages * page_size
            except Exception:
                return total, 0
    if os.path.exists("/proc/meminfo"):
        try:
            values: dict[str, int] = {}
            with open("/proc/meminfo", "r", encoding="utf-8") as fh:
                for line in fh:
                    key, raw = line.split(":", 1)
                    number = raw.strip().split()[0]
                    if number.isdigit():
                        values[key] = int(number) * 1024
            return values.get("MemTotal", 0), values.get("MemAvailable", values.get("MemFree", 0))
        except Exception:
            pass
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        total_pages = os.sysconf("SC_PHYS_PAGES")
        avail_pages = os.sysconf("SC_AVPHYS_PAGES")
        return int(page_size * total_pages), int(page_size * avail_pages)
    except Exception:
        return 0, 0


def sys_platform() -> str:
    import sys
    return sys.platform


def _nvidia() -> list[dict[str, Any]]:
    smi = shutil.which("nvidia-smi")
    if not smi and os.name == "nt":
        candidate = r"C:\Windows\System32\nvidia-smi.exe"
        if os.path.exists(candidate):
            smi = candidate
    if not smi:
        return []
    cp = _run([
        smi, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"
    ])
    if not cp or cp.returncode != 0:
        return []
    out: list[dict[str, Any]] = []
    for line in cp.stdout.splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            vram = int(float(parts[1]))
        except Exception:
            vram = 0
        out.append({"vendor": "nvidia", "name": parts[0], "vram_mb": vram, "driver": parts[2] if len(parts) > 2 else "", "backend": "cuda"})
    return out


def _amd() -> list[dict[str, Any]]:
    rocm = shutil.which("rocm-smi")
    if rocm:
        cp = _run([rocm, "--showproductname", "--showmeminfo", "vram", "--json"], timeout=4.0)
        if cp and cp.returncode == 0:
            try:
                data = json.loads(cp.stdout)
                out: list[dict[str, Any]] = []
                for _, item in data.items():
                    if not isinstance(item, dict):
                        continue
                    name = next((str(v) for k, v in item.items() if "Card series" in k or "Card model" in k), "AMD GPU")
                    raw = next((v for k, v in item.items() if "VRAM Total Memory" in k), 0)
                    digits = "".join(ch for ch in str(raw) if ch.isdigit())
                    total = int(digits or 0)
                    # rocm-smi can report bytes.
                    vram_mb = total // (1024 * 1024) if total > 10_000_000 else total
                    out.append({"vendor": "amd", "name": name, "vram_mb": vram_mb, "backend": "rocm"})
                if out:
                    return out
            except Exception:
                pass
    return []


def _is_integrated_gpu(vendor: str, name: str, vram_mb: int = 0) -> bool:
    low = str(name or "").lower()
    normalized = low.replace("(tm)", "")
    vendor = str(vendor or "").lower()
    if vendor == "intel":
        # Intel Arc A/B-series names are discrete; plain "Arc Graphics", Iris and
        # UHD branding are integrated/shared-memory adapters. Tiny AdapterRAM
        # values reported by Windows are not usable as dedicated-VRAM capacity.
        if re.search(r"\barc(?:\(tm\))?\s+(?:pro\s+)?[ab]\d{2,4}m?\b", low) or "arc pro" in low:
            return False
        return any(token in normalized for token in ("arc graphics", "iris", "uhd", "integrated")) or int(vram_mb or 0) < 1024
    if vendor == "amd":
        # Windows may expose Ryzen APUs only as "AMD Radeon (TM) Graphics".
        # Match that complete generic name, never RX/Pro/R-series discrete GPUs.
        generic_apu = re.fullmatch(r"(?:amd\s+)?radeon\s+graphics", " ".join(normalized.split()))
        return bool(generic_apu or re.search(r"\bradeon\s+\d{3,4}m\b", normalized)) or "integrated" in low
    return False


def _openvino_devices() -> list[dict[str, Any]]:
    try:
        from .accelerators import openvino_runtime
        runtime = openvino_runtime()
    except Exception:
        return []
    names = runtime.get("device_names", {}) if isinstance(runtime, dict) else {}
    out: list[dict[str, Any]] = []
    for device in runtime.get("devices", []) if isinstance(runtime, dict) else []:
        name = str(names.get(device, device)) if isinstance(names, dict) else str(device)
        family = str(device).split(".", 1)[0].upper()
        if family in {"NPU", "GPU"}:
            out.append({"vendor": "intel", "device": str(device), "kind": family.lower(), "name": name, "backend": "openvino", "runtime_available": True})
    return out


def _windows_npus() -> list[dict[str, Any]]:
    if os.name != "nt" or not shutil.which("powershell"):
        return []
    script = (
        "Get-CimInstance Win32_PnPEntity | "
        "Where-Object { $_.Name -match '\\b(?:NPU|AI Boost|Neural Processing)\\b' } | "
        "Select-Object Name,Manufacturer,Status | ConvertTo-Json -Compress"
    )
    cp = _run(["powershell", "-NoProfile", "-Command", script], timeout=4.0)
    if not cp or cp.returncode != 0 or not cp.stdout.strip():
        return []
    try:
        data = json.loads(cp.stdout)
    except Exception:
        return []
    items = data if isinstance(data, list) else [data]
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or not item.get("Name"):
            continue
        name = str(item.get("Name"))
        vendor = "intel" if "intel" in (name + " " + str(item.get("Manufacturer", ""))).lower() else "unknown"
        out.append({"vendor": vendor, "name": name, "backend": "openvino", "device": "NPU", "runtime_available": False, "status": str(item.get("Status", ""))})
    return out


def _intel() -> list[dict[str, Any]]:
    xpu = shutil.which("xpu-smi")
    if not xpu:
        return []
    cp = _run([xpu, "discovery", "-j"], timeout=4.0)
    if not cp or cp.returncode != 0:
        return []
    try:
        data = json.loads(cp.stdout)
    except Exception:
        return []
    devices = data.get("device_list", data if isinstance(data, list) else [])
    out: list[dict[str, Any]] = []
    if isinstance(devices, list):
        for item in devices:
            if isinstance(item, dict):
                name = str(item.get("device_name") or item.get("name") or "Intel GPU")
                vram_mb = int(item.get("memory_physical_size_byte", 0) or 0) // (1024 * 1024)
                out.append({"vendor": "intel", "name": name, "vram_mb": vram_mb, "backend": "oneapi", "integrated": _is_integrated_gpu("intel", name, vram_mb), "shared_memory": _is_integrated_gpu("intel", name, vram_mb)})
    return out


def _apple(total_ram_bytes: int) -> list[dict[str, Any]]:
    if sys_platform() != "darwin" or platform.machine().lower() not in {"arm64", "aarch64"}:
        return []
    cp = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
    name = cp.stdout.strip() if cp and cp.returncode == 0 else "Apple Silicon"
    # Apple GPUs use unified memory. Keep total memory explicit rather than pretending it is dedicated VRAM.
    return [{"vendor": "apple", "name": name, "vram_mb": 0, "unified_memory_mb": total_ram_bytes // (1024 * 1024), "backend": "metal", "integrated": True}]


def _generic_windows() -> list[dict[str, Any]]:
    if os.name != "nt" or not shutil.which("powershell"):
        return []
    script = "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM | ConvertTo-Json -Compress"
    cp = _run(["powershell", "-NoProfile", "-Command", script], timeout=4.0)
    if not cp or cp.returncode != 0 or not cp.stdout.strip():
        return []
    try:
        data = json.loads(cp.stdout)
    except Exception:
        return []
    items = data if isinstance(data, list) else [data]
    out = []
    for item in items:
        if not isinstance(item, dict) or not item.get("Name"):
            continue
        name = str(item["Name"])
        low = name.lower()
        vendor = "intel" if "intel" in low else "amd" if ("amd" in low or "radeon" in low) else "nvidia" if "nvidia" in low else "unknown"
        ram = int(item.get("AdapterRAM") or 0)
        vram_mb = ram // (1024 * 1024) if ram else 0
        integrated = _is_integrated_gpu(vendor, name, vram_mb)
        out.append({"vendor": vendor, "name": name, "vram_mb": vram_mb, "backend": "windows", "integrated": integrated, "shared_memory": integrated})
    return out


def choose_profile(gpus: list[dict[str, Any]], ram_gb: float, requested: str = "auto") -> str:
    requested = str(requested or "auto").strip().lower()
    if requested in {"cpu", "integrated", "low", "balanced", "high", "max"}:
        return requested
    apple = next((g for g in gpus if g.get("vendor") == "apple"), None)
    if apple:
        unified = float(apple.get("unified_memory_mb", 0)) / 1024.0
        if unified >= 64:
            return "max"
        if unified >= 32:
            return "high"
        if unified >= 16:
            return "balanced"
        return "low"
    integrated = [g for g in gpus if bool(g.get("integrated"))]
    dedicated = max((int(g.get("vram_mb", 0) or 0) for g in gpus if not bool(g.get("integrated"))), default=0)
    if dedicated >= 20 * 1024:
        return "max"
    if dedicated >= 12 * 1024:
        return "high"
    if dedicated >= 6 * 1024:
        return "balanced"
    if dedicated > 0:
        return "low"
    # Shared-memory iGPUs must not be sized from Windows AdapterRAM.  A 32 GB
    # Core Ultra notebook is useful, but running 7B models plus a second local
    # worker is too aggressive for an iGPU that competes with system memory.
    if integrated:
        return "integrated" if ram_gb >= 16 else "cpu"
    return "low" if ram_gb >= 16 else "cpu"


@lru_cache(maxsize=4)
def detect_hardware(requested_profile: str = "auto") -> dict[str, Any]:
    total, available = _memory_bytes()
    gpus = _nvidia() or _amd() or _intel()
    if not gpus:
        gpus = _apple(total) or _generic_windows()
    total_gb = round(total / (1024 ** 3), 1) if total else 0.0
    profile_name = choose_profile(gpus, total_gb, requested_profile)

    ov_devices = _openvino_devices()
    runtime_npus = [dict(item) for item in ov_devices if item.get("kind") == "npu"]
    physical_npus = _windows_npus()
    npus = runtime_npus or physical_npus
    if runtime_npus and physical_npus:
        for item in npus:
            item["hardware_detected"] = True
    openvino_gpu_devices = [dict(item) for item in ov_devices if item.get("kind") == "gpu"]

    # Some Windows builds expose incomplete VideoController memory/type metadata
    # while the Meteor/Arrow/Lunar Lake NPU is still discoverable.  An Intel NPU
    # plus no dedicated GPU is a strong signal for the shared-memory notebook
    # profile, but never overrides an explicit user-selected profile.
    requested_norm = str(requested_profile or "auto").strip().lower()
    dedicated_vram = max((int(g.get("vram_mb", 0) or 0) for g in gpus if not bool(g.get("integrated"))), default=0)
    intel_npu = any(str(item.get("vendor", "")).lower() == "intel" for item in npus if isinstance(item, dict))
    if requested_norm == "auto" and intel_npu and dedicated_vram <= 0 and total_gb >= 16:
        profile_name = "integrated"

    return {
        "platform": sys_platform(),
        "os": platform.system().lower(),
        "arch": platform.machine().lower(),
        "cpu": {"name": platform.processor() or platform.machine(), "logical_cores": os.cpu_count() or 1},
        "ram": {"total_gb": total_gb, "available_gb": round(available / (1024 ** 3), 1) if available else 0.0},
        "gpus": gpus,
        "npus": npus,
        "openvino_devices": ov_devices,
        "openvino_gpu_devices": openvino_gpu_devices,
        "profile": profile_name,
    }


PROFILE_OVERRIDES: dict[str, dict[str, Any]] = {
    "cpu": {
        "models": {
            "background_code": "qwen2.5-coder:0.5b",
            "fast_code": "qwen2.5-coder:1.5b",
            "heavy_code": "qwen2.5-coder:3b",
            "reasoning": "qwen2.5-coder:7b",
            "general": "qwen2.5-coder:1.5b",
            "vision": "qwen3-vl:4b",
        },
        "features": {"reranker": True},
        "scheduler": {"max_parallel": 1, "max_inflight_per_tenant": 1, "max_loaded_models": 1},
        "ollama": {
            "num_parallel": 1,
            "kv_cache_type": "q4_0",
            "keep_alive": "5m",
            "flash_attention": True,
            "num_threads": max(1, (os.cpu_count() or 4) - 2),
        },
        "background_gpu": {"enabled": False, "parallel": 1},
        "cpu_retrieval": {"embedding_batch_size": 4, "reranker_batch_size": 2, "reranker_max_length": 512, "embedding_trust_remote_code": False},
        "deterministic": {"context_raw_evidence": 3, "context_max_chars": 3600},
        "search": {"context_top_k": 8, "max_snippets_per_file": 2},
        "rag": {"rerank_candidates": 8},
        "execution_planner": {"direct_confidence": 0.85, "worker_below_confidence": 0.72},
        "model_execution": {
            "background": {"parallel": 1, "context_tokens": 8192, "max_context_tokens": 16384, "max_prompt_tokens": 7000},
            "fast": {"parallel": 1, "context_tokens": 16384, "max_context_tokens": 24576, "max_prompt_tokens": 14000},
            "smart": {"parallel": 1, "context_tokens": 16384, "max_context_tokens": 24576, "max_prompt_tokens": 14000},
        },
        "preprocessing": {
            "cpu_workers": 1,
            "cpu_worker_sleep_seconds": 0.20,
            "idle_grace_seconds": 30.0,
        },
        "local_pipeline": {
            "same_model_worker_passes": 1,
        },
        "ollama_subagents": {"profiles": {
            "qwen-explorer": {"model": "qwen2.5-coder:1.5b"},
            "qwen-drafter": {"model": "qwen2.5-coder:3b"},
            "qwen-critic": {"model": "qwen2.5-coder:7b"},
        }},
    },
    "integrated": {
        "models": {
            "background_code": "qwen2.5-coder:0.5b",
            "fast_code": "qwen2.5-coder:1.5b",
            "heavy_code": "qwen2.5-coder:3b",
            "reasoning": "qwen2.5-coder:7b",
            "general": "qwen2.5-coder:1.5b",
            "vision": "qwen3-vl:4b",
        },
        "scheduler": {"max_parallel": 1, "max_loaded_models": 1, "max_queue": 32, "max_queued_per_tenant": 12, "max_inflight_per_tenant": 1},
        # Keep shared-memory systems serial. Intel inference is routed to the
        # optional llama.cpp SYCL server; no Ollama fallback is implied. AMD
        # integrated GPUs retain the existing Vulkan path when explicitly used.
        "ollama": {
            "num_parallel": 1,
            "allow_integrated_gpu": True,
            "enable_vulkan": True,
            "gpu_overhead_bytes": 1073741824,
            "kv_cache_type": "q4_0",
            "keep_alive": "5m",
            "flash_attention": True,
            "num_threads": max(1, (os.cpu_count() or 4) - 2),
        },
        "background_gpu": {"enabled": False, "parallel": 1, "file_batch_size": 1, "module_batch_size": 1},
        "cpu_retrieval": {"embedding_batch_size": 4, "reranker_batch_size": 2, "reranker_max_length": 512, "embedding_trust_remote_code": False},
        "deterministic": {"context_raw_evidence": 3, "context_max_chars": 3600},
        "search": {"context_top_k": 8, "max_snippets_per_file": 2},
        "rag": {"rerank_candidates": 8},
        "execution_planner": {"direct_confidence": 0.85, "worker_below_confidence": 0.72},
        "local_pipeline": {
            "same_model_worker_passes": 1,
        },
        "model_execution": {
            "background": {"parallel": 1, "context_tokens": 4096, "max_context_tokens": 8192, "max_prompt_tokens": 3500},
            "fast": {"parallel": 1, "context_tokens": 8192, "max_context_tokens": 12288, "max_prompt_tokens": 7000},
            "smart": {"parallel": 1, "context_tokens": 8192, "max_context_tokens": 12288, "max_prompt_tokens": 7000},
            "generic": {"parallel": 1, "context_tokens": 8192, "max_context_tokens": 12288, "max_prompt_tokens": 7000},
        },
        "ollama_subagents": {
            "profiles": {
        "qwen-explorer": {"model": "qwen2.5-coder:1.5b"},
        "qwen-drafter": {"model": "qwen2.5-coder:3b"},
        "qwen-critic": {"model": "qwen2.5-coder:7b"},
            }
        },
        "preprocessing": {
            "idle_grace_seconds": 30.0,
            "max_preprocessing_projects": 1,
            "cpu_workers": 1,
            "rag_files_per_step": 6,
            "cpu_worker_sleep_seconds": 0.20,
        },
        "prewarm": {"enabled": False},
        "async_jobs": {"max_pending": 16},
        "code_intelligence": {"max_sessions_per_backend": 2},
        "headless": {"max_sessions_per_backend": 2},
        "debug_traces": {"max_bytes": 134217728, "max_sessions": 300},
        "work_orchestrator": {
            "max_active_work_orders": 1, "max_steps": 32, "max_llm_steps": 16,
            "max_pending_work_orders": 8, "worker_idle_seconds": 30,
            "parallel_llm_steps": 1, "parallel_deterministic_steps": 2, "step_retry_limit": 2,
        },
    },
    "low": {
        "models": {
            "background_code": "qwen2.5-coder:0.5b",
            "fast_code": "qwen2.5-coder:1.5b",
            "heavy_code": "qwen2.5-coder:3b",
            "reasoning": "qwen2.5-coder:7b",
            "general": "qwen2.5-coder:1.5b",
            "vision": "qwen3-vl:4b",
        },
        "scheduler": {"max_parallel": 1, "max_inflight_per_tenant": 1},
        "ollama": {"num_parallel": 1},
        "background_gpu": {"parallel": 1, "file_batch_size": 1, "module_batch_size": 1},
        "cpu_retrieval": {"embedding_batch_size": 6, "reranker_batch_size": 2},
        "model_execution": {
            "background": {"parallel": 1, "context_tokens": 16384, "max_context_tokens": 24576, "max_prompt_tokens": 14000},
            "fast": {"parallel": 1, "context_tokens": 24576, "max_context_tokens": 32768, "max_prompt_tokens": 22000},
            "smart": {"parallel": 1, "context_tokens": 24576, "max_context_tokens": 32768, "max_prompt_tokens": 22000},
        },
        "ollama_subagents": {"profiles": {
            "qwen-explorer": {"model": "qwen2.5-coder:1.5b"},
            "qwen-drafter": {"model": "qwen2.5-coder:3b"},
            "qwen-critic": {"model": "qwen2.5-coder:7b"},
        }},
    },
    "balanced": {
        "models": {
            "background_code": "qwen2.5-coder:0.5b",
            "fast_code": "qwen2.5-coder:1.5b",
            "heavy_code": "qwen2.5-coder:7b",
            "reasoning": "qwen2.5-coder:7b",
            "general": "qwen2.5-coder:7b",
            "vision": "qwen3.5:9b",
        },
        "scheduler": {"max_parallel": 2, "max_inflight_per_tenant": 2},
        "ollama": {"num_parallel": 2},
        "background_gpu": {"parallel": 2, "file_batch_size": 2, "module_batch_size": 2},
        "cpu_retrieval": {"embedding_batch_size": 12, "reranker_batch_size": 4},
    },
    "high": {
        "models": {
            "background_code": "qwen2.5-coder:0.5b",
            "fast_code": "qwen2.5-coder:1.5b",
            "heavy_code": "qwen2.5-coder:3b",
            "reasoning": "qwen2.5-coder:7b",
            "general": "qwen3.5:9b",
            "vision": "qwen3.5:9b",
        },
        "scheduler": {"max_parallel": 3, "max_inflight_per_tenant": 3},
        "ollama": {"num_parallel": 3},
        "background_gpu": {"parallel": 3, "file_batch_size": 3, "module_batch_size": 3},
        "cpu_retrieval": {"embedding_batch_size": 20, "reranker_batch_size": 6},
    },
    "max": {
        "models": {
            "background_code": "qwen2.5-coder:0.5b",
            "fast_code": "qwen2.5-coder:1.5b",
            "heavy_code": "qwen2.5-coder:3b",
            "reasoning": "qwen2.5-coder:7b",
            "general": "qwen3.5:9b",
            "vision": "qwen3.5:9b",
        },
        "scheduler": {"max_parallel": 4, "max_inflight_per_tenant": 4},
        "ollama": {"num_parallel": 4},
        "background_gpu": {"parallel": 4, "file_batch_size": 4, "module_batch_size": 4},
        "cpu_retrieval": {"embedding_batch_size": 32, "reranker_batch_size": 8},
    },
}


def profile_overrides(profile_name: str, detected: dict[str, Any] | None = None) -> dict[str, Any]:
    import copy
    result = copy.deepcopy(PROFILE_OVERRIDES.get(profile_name, PROFILE_OVERRIDES["balanced"]))
    detected = detected or {}
    ram_gb = float(detected.get("ram", {}).get("total_gb", 0) or 0)
    if profile_name == "integrated":
        gpus = detected.get("gpus", [])
        has_intel_gpu = any(
            str(gpu.get("vendor", "")).lower() == "intel"
            or "intel" in str(gpu.get("name", "")).lower()
            for gpu in gpus if isinstance(gpu, dict)
        ) if isinstance(gpus, list) else False
        if has_intel_gpu:
            result = _deep_merge_dict(result, {"ollama": {"allow_integrated_gpu": False, "enable_vulkan": False}})
        if ram_gb >= 24:
            # 32 GB shared-memory laptops support all four configured model tiers.
            result = _deep_merge_dict(result, {
                "model_execution": {
                    "fast": {"context_tokens": 32768, "max_context_tokens": 32768, "max_prompt_tokens": 24000},
                    "smart": {"context_tokens": 32768, "max_context_tokens": 32768, "max_prompt_tokens": 24000},
                    "generic": {"context_tokens": 32768, "max_context_tokens": 32768, "max_prompt_tokens": 24000},
                }
            })
        elif ram_gb >= 16:
            # 16 GB shared memory laptops scale comfortably to 16k context
            result = _deep_merge_dict(result, {
                "model_execution": {
                    "fast": {"context_tokens": 16384, "max_context_tokens": 24576, "max_prompt_tokens": 14000},
                    "smart": {"context_tokens": 16384, "max_context_tokens": 24576, "max_prompt_tokens": 14000},
                    "generic": {"context_tokens": 16384, "max_context_tokens": 24576, "max_prompt_tokens": 14000},
                }
            })
    intel_integrated = any(
        str(gpu.get("vendor", "")).lower() == "intel" and bool(gpu.get("integrated"))
        for gpu in detected.get("gpus", []) if isinstance(gpu, dict)
    )
    has_npu = bool(detected.get("npus"))
    if (profile_name in ("integrated", "cpu") and has_npu) or (profile_name == "integrated" and intel_integrated):
        # Retrieval models are small enough to be useful on Intel/AMD NPU/iGPU while
        # leaving the shared-memory LLM lane serial and conservative. Runtime
        # failures fall back to the next OpenVINO device and finally CPU.
        result = _deep_merge_dict(result, {
            "models": {
                "embedding": "BAAI/bge-small-en-v1.5",
                "embedding_backend": "openvino", "embedding_device": "auto",
                "reranker": "cross-encoder/ms-marco-MiniLM-L6-v2",
                "reranker_backend": "openvino", "reranker_device": "auto",
            },
            "openvino": {"enabled": True},
        })
    return result


def _deep_merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    import copy
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge_dict(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result
