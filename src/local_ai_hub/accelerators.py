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
    cfg = config.get("openvino", {}) if isinstance(config, dict) else {}
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


def openvino_cache_dir(config: dict[str, Any]) -> Path | None:
    cfg = config.get("openvino", {}) if isinstance(config, dict) else {}
    raw = str(cfg.get("cache_dir", "") or "").strip()
    if not raw:
        return None
    path = Path(os.path.expandvars(os.path.expanduser(raw)))
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return path


def accelerator_status(config: dict[str, Any]) -> dict[str, Any]:
    runtime = openvino_runtime()
    models = config.get("models", {}) if isinstance(config, dict) else {}
    return {
        "openvino": runtime,
        "embedding": {
            "backend": models.get("embedding_backend", "sentence-transformers"),
            "requested_device": models.get("embedding_device", "cpu"),
            "candidates": openvino_device_candidates(config, str(models.get("embedding_device", "auto"))),
        },
        "reranker": {
            "backend": models.get("reranker_backend", "torch"),
            "requested_device": models.get("reranker_device", "cpu"),
            "candidates": openvino_device_candidates(config, str(models.get("reranker_device", "auto"))),
        },
    }
