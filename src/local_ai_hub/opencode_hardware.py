"""Conservative capacity hints for the OpenCode local installation.

These are not inference admission or benchmark results. Callers must verify the
model, backend, free memory, context and GPU concurrency before selecting it.
"""
from __future__ import annotations

from typing import Any

from .opencode_model_names import validate_local_model_name

# Driver inventories can reserve part of the board's nominal VRAM. A 16 GiB
# RTX 5070 Ti with driver 621.01 reported 16303 MiB, 81 MiB below nominal.
# This tolerance is only for labelling candidates, never for memory admission.
_CAPACITY_MB = {"12gb": 12 * 1024 - 32, "16gb": 16 * 1024 - 128}
_CANDIDATES = {
    "12gb": ("qwen3.5:9b", "qwen2.5-coder:7b"),
    "16gb": ("qwen3.5:9b-nvfp4", "qwen2.5-coder:7b", "qwen3.5:4b-nvfp4"),
}


def future_profile_candidates(profile: str, *, model: str | None = None) -> list[str]:
    """List staging candidates without asserting current GPU eligibility."""
    if not isinstance(profile, str) or profile not in _CANDIDATES:
        raise ValueError("future profile must be 12gb or 16gb")
    names = list(_CANDIDATES[profile])
    if model is not None:
        validate_local_model_name(model)
        names = [model, *(name for name in names if name != model)]
    return names


def inspect_opencode_hardware(
    hardware: dict[str, Any], *, requested: str = "auto", model: str | None = None,
) -> dict[str, Any]:
    """Describe a single dedicated GPU's capacity, without approving inference."""
    if not isinstance(requested, str) or requested not in {"auto", "12gb", "16gb"}:
        raise ValueError("profile must be auto, 12gb or 16gb")
    if model is not None:
        validate_local_model_name(model)
    rows = hardware.get("gpus", []) if isinstance(hardware, dict) else []
    if not isinstance(rows, list):
        rows = []
    candidates = []
    for gpu in rows:
        if not isinstance(gpu, dict) or not isinstance(gpu.get("vendor"), str) or gpu["vendor"] not in {"nvidia", "amd", "intel"}:
            continue
        if gpu.get("integrated", False) is not False or gpu.get("shared_memory", False) is not False:
            continue
        memory = gpu.get("vram_mb")
        if type(memory) is not int or memory < 0:
            continue
        candidates.append(gpu)
    selected_gpu = max(candidates, key=lambda item: item["vram_mb"], default=None)
    memory = selected_gpu["vram_mb"] if selected_gpu else 0
    detected = "16gb" if memory >= _CAPACITY_MB["16gb"] else "12gb" if memory >= _CAPACITY_MB["12gb"] else "unsupported"
    if requested != "auto" and memory < _CAPACITY_MB[requested]:
        raise ValueError(f"{requested} profile exceeds detected dedicated GPU capacity")
    profile = detected if requested == "auto" else requested
    names = list(_CANDIDATES.get(profile, ()))
    if model is not None:
        names = [model, *(name for name in names if name != model)]
    return {
        "profile": profile,
        "detected_profile": detected,
        "gpu": dict(selected_gpu) if selected_gpu else None,
        "candidates": names,
        "selected_model": None,
        "runtime_verified": False,
        "admission": "unverified",
        "reason": ("dedicated_gpu_not_detected" if selected_gpu is None else
                   "dedicated_vram_unknown" if memory == 0 else
                   "dedicated_vram_below_12gb" if detected == "unsupported" else
                   "runtime_validation_required"),
    }
