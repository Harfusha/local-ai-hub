from __future__ import annotations

from typing import Any


def resolve_runtime(*, device: str = "cuda", torch_module: Any | None = None) -> dict[str, Any]:
    """Resolve accelerated training settings; a CUDA request never falls back silently."""
    if torch_module is None:
        try:
            import torch as torch_module
        except ImportError as exc:
            raise RuntimeError("PyTorch is required; install the model-training environment") from exc
    if device not in {"cuda", "cpu"}:
        raise ValueError("device must be cuda or cpu; choose cpu explicitly")
    cuda_available = bool(torch_module.cuda.is_available())
    if device == "cuda" and not cuda_available:
        raise RuntimeError("CUDA requested but unavailable; no CPU fallback was used")
    if device == "cpu":
        return {
            "device": "cpu",
            "precision": "fp32",
            "dtype": torch_module.float32,
            "attention": "eager",
            "fused_optimizer": False,
        }

    supports_bf16 = bool(getattr(torch_module.cuda, "is_bf16_supported", lambda: False)())
    dtype = torch_module.bfloat16 if supports_bf16 else torch_module.float16
    sdpa = getattr(getattr(torch_module.nn, "functional", None), "scaled_dot_product_attention", None)
    return {
        "device": "cuda",
        "precision": "bf16" if supports_bf16 else "fp16",
        "dtype": dtype,
        "attention": "sdpa" if sdpa is not None else "eager",
        "fused_optimizer": True,
    }
