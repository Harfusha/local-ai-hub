from __future__ import annotations

import importlib.util
import os
from functools import lru_cache
from pathlib import Path
from typing import Any


def _normalise_device(value: str) -> str:
    return str(value or "").strip().upper()


@lru_cache(maxsize=1)
def openvino_runtime() -> dict[str, Any]:
    """Return a dependency-light snapshot of OpenVINO accelerator availability.

    The hub treats OpenVINO as an optional accelerator. Import/driver failures are
    diagnostic state, never startup failures, so CPU/Ollama paths stay available.
    """
    if importlib.util.find_spec("openvino") is None:
        return {"installed": False, "available": False, "devices": [], "error": "openvino is not installed"}
    try:
        import openvino as ov

        core = ov.Core()
        devices = [str(device) for device in core.available_devices]
        names: dict[str, str] = {}
        for device in devices:
            try:
                names[device] = str(core.get_property(device, "FULL_DEVICE_NAME"))
            except Exception:
                names[device] = device
        return {
            "installed": True,
            "available": bool(devices),
            "version": str(getattr(ov, "__version__", "")),
            "devices": devices,
            "device_names": names,
        }
    except Exception as exc:
        return {
            "installed": True,
            "available": False,
            "devices": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


def reset_openvino_probe_cache() -> None:
    openvino_runtime.cache_clear()


def openvino_device_candidates(config: dict[str, Any], requested: str = "auto") -> list[str]:
    """Resolve actual OpenVINO devices in preference order.

    NPU is intentionally explicit because OpenVINO AUTO does not include NPU in
    its default priority list. Local AI Hub therefore probes NPU first when the
    user/profile asks for automatic Intel acceleration, then Intel GPU, then CPU.
    """
    cfg_raw = config.get("openvino") if isinstance(config, dict) else None
    cfg = cfg_raw if isinstance(cfg_raw, dict) else {}
    if cfg.get("enabled", True) is False:
        return []
    runtime = openvino_runtime()
    available = [str(item) for item in runtime.get("devices", [])]
    if not available:
        return []

    requested_norm = _normalise_device(requested)
    if requested_norm and requested_norm not in {"AUTO", "OPENVINO"}:
        exact = [device for device in available if _normalise_device(device) == requested_norm]
        if exact:
            return exact
        family = [device for device in available if _normalise_device(device).split(".", 1)[0] == requested_norm.split(".", 1)[0]]
        if family:
            return family

    raw_priority = cfg.get("device_priority", ["NPU", "GPU", "CPU"])
    priorities = [str(item).upper() for item in raw_priority] if isinstance(raw_priority, list) else ["NPU", "GPU", "CPU"]
    result: list[str] = []
    for family in priorities:
        for device in available:
            upper = _normalise_device(device)
            if (upper == family or upper.startswith(family + ".")) and device not in result:
                result.append(device)
    for device in available:
        if device not in result:
            result.append(device)
    return result


def _torch_gpu_route() -> tuple[str, str] | None:
    """Return a usable Torch GPU route without making Torch a required dependency."""
    try:
        import torch

        if bool(torch.cuda.is_available()):
            # PyTorch exposes supported AMD ROCm devices through its CUDA API too.
            # Keep the logical device as `cuda`; the installed Torch build owns the
            # actual vendor runtime selection.
            return "sentence-transformers", "cuda"
    except Exception:
        pass
    return None


def _onnx_providers() -> set[str]:
    try:
        import onnxruntime as ort

        return {str(item) for item in ort.get_available_providers()}
    except Exception:
        return set()


def automatic_embedding_candidates(config: dict[str, Any]) -> list[tuple[str, str]]:
    """Probe installed accelerator runtimes and return routes in policy order.

    Discovery is intentionally based on runnable provider APIs, not hardware
    profile labels. A candidate is still validated by loading the model; callers
    retain CPU fallback when an installed provider cannot compile it.
    """
    candidates: list[tuple[str, str]] = []
    try:
        from .hardware import detect_hardware

        hardware = detect_hardware("auto")
    except Exception:
        hardware = {}
    npus = hardware.get("npus", []) if isinstance(hardware, dict) else []
    gpus = hardware.get("gpus", []) if isinstance(hardware, dict) else []
    openvino_devices = openvino_device_candidates(config, "auto")

    # NPU routes always precede GPU routes. OpenVINO's NPU plugin is currently
    # the native Intel path; Vitis AI is used only when its ORT provider exists.
    if any(str(device).upper().startswith("NPU") for device in openvino_devices):
        candidates.append(("openvino", next(device for device in openvino_devices if str(device).upper().startswith("NPU"))))
    if any(isinstance(item, dict) and str(item.get("vendor", "")).lower() == "amd" for item in npus):
        if "VitisAIExecutionProvider" in _onnx_providers():
            candidates.append(("onnx-vitisai", "VitisAIExecutionProvider"))

    # CUDA is the preferred dGPU path for NVIDIA and supported AMD ROCm builds.
    torch_route = _torch_gpu_route()
    torch_gpu_candidate: tuple[str, str] | None = None
    discrete: list[dict[str, Any]] = []
    if torch_route is not None:
        try:
            import torch

            is_amd_rocm = bool(getattr(getattr(torch, "version", None), "hip", None))
            torch_name = str(torch.cuda.get_device_name(0) or "")
        except Exception:
            is_amd_rocm = False
            torch_name = ""
        vendor = "amd" if is_amd_rocm else "nvidia"
        vendor_gpus = [item for item in gpus if isinstance(item, dict) and str(item.get("vendor", "")).lower() == vendor]
        discrete = [item for item in vendor_gpus if not bool(item.get("integrated"))]
        integrated = [item for item in vendor_gpus if bool(item.get("integrated"))]
        if not vendor_gpus and torch_name:
            try:
                from .hardware import _is_integrated_gpu

                is_integrated = _is_integrated_gpu(vendor, torch_name)
            except Exception:
                is_integrated = False
            (integrated if is_integrated else discrete).append({"vendor": vendor, "name": torch_name})
        target = discrete or integrated
        torch_gpu_candidate = torch_route if target else None
        if discrete and torch_gpu_candidate is not None:
            candidates.append(torch_gpu_candidate)

    # Classify OpenVINO GPU device names so Intel Arc dGPUs remain ahead of
    # shared-memory iGPUs when both are present.
    runtime = openvino_runtime()
    names = runtime.get("device_names", {}) if isinstance(runtime, dict) else {}
    openvino_discrete: list[tuple[str, str]] = []
    openvino_integrated: list[tuple[str, str]] = []
    for device in openvino_devices:
        if not str(device).upper().startswith("GPU"):
            continue
        name = str(names.get(device, device)) if isinstance(names, dict) else str(device)
        try:
            from .hardware import _is_integrated_gpu

            is_integrated = _is_integrated_gpu("intel", name)
        except Exception:
            is_integrated = False
        (openvino_integrated if is_integrated else openvino_discrete).append(("openvino", device))
    candidates.extend(openvino_discrete)

    # A DirectML device is ranked as dedicated if hardware inventory finds any
    # dedicated adapter; otherwise it joins the integrated-GPU tier.
    directml = "DmlExecutionProvider" in _onnx_providers() and bool(gpus)
    has_dedicated_gpu = any(isinstance(item, dict) and not bool(item.get("integrated")) for item in gpus)
    if directml and has_dedicated_gpu:
        candidates.append(("onnx-directml", "DmlExecutionProvider"))

    # A supported ROCm APU may expose only an integrated GPU. Place it after
    # dedicated routes and alongside the integrated OpenVINO/DX12 choices.
    if torch_gpu_candidate is not None and not discrete:
        candidates.append(torch_gpu_candidate)

    candidates.extend(openvino_integrated)
    # DirectML is the broad Windows DX12 route for detected integrated adapters.
    # ONNX Runtime chooses its default adapter; explicit device pinning remains
    # available through vendor-native routes where the runtime exposes it.
    if directml and not has_dedicated_gpu:
        candidates.append(("onnx-directml", "DmlExecutionProvider"))

    # Stable de-duplication; CPU is appended by EmbeddingModel under auto policy.
    result: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for backend, device in candidates:
        key = (backend, str(device).upper())
        if key not in seen:
            seen.add(key)
            result.append((backend, device))
    return result


def openvino_cache_dir(config: dict[str, Any]) -> Path | None:
    cfg = config.get("openvino") if isinstance(config, dict) else None
    if not isinstance(cfg, dict):
        return None
    raw = str(cfg.get("cache_dir", "") or "").strip()
    if not raw or "\0" in raw:
        return None
    try:
        path = Path(os.path.expandvars(os.path.expanduser(raw)))
        path.mkdir(parents=True, exist_ok=True)
        return path
    except (ValueError, OSError):
        return None


def accelerator_status(config: dict[str, Any]) -> dict[str, Any]:
    runtime = openvino_runtime()
    models_raw = config.get("models") if isinstance(config, dict) else None
    models = models_raw if isinstance(models_raw, dict) else {}
    return {
        "openvino": runtime,
        "embedding": {
            "backend": models.get("embedding_backend", "sentence-transformers"),
            "requested_device": models.get("embedding_device", "cpu"),
            "candidates": [*automatic_embedding_candidates(config), ("sentence-transformers", "cpu")]
            if str(models.get("embedding_backend", "")).lower() == "auto"
            else openvino_device_candidates(config, str(models.get("embedding_device", "auto"))),
            "onnx_providers": sorted(_onnx_providers()),
            "torch_gpu_available": _torch_gpu_route() is not None,
        },
        "reranker": {
            "backend": models.get("reranker_backend", "torch"),
            "requested_device": models.get("reranker_device", "cpu"),
            "candidates": [
                ("torch" if backend == "sentence-transformers" else backend, device)
                for backend, device in automatic_embedding_candidates(config)
            ] + [("torch", "cpu")]
            if str(models.get("reranker_backend", "")).lower() == "auto"
            else openvino_device_candidates(config, str(models.get("reranker_device", "auto"))),
        },
    }
