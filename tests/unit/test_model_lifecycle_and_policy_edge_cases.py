from __future__ import annotations

import threading

from local_ai_hub.model_lifecycle import (
    acquire_locks,
    active_cuda_model_count,
    is_cuda_model_registered,
    load_model,
    release_model,
    uses_torch_cuda,
)
from local_ai_hub.model_policy import ExecutionProfile, ModelExecutionPolicy


class _DummyOwner:
    pass


def test_model_lifecycle_locks_cuda_detection_and_weakref_safety() -> None:
    lock_a = threading.Lock()
    lock_b = threading.Lock()

    with acquire_locks((lock_a, lock_b), float("nan")) as ok:
        assert ok is True
    with acquire_locks((lock_a, lock_b), float("inf")) as ok:
        assert ok is True
    with acquire_locks(None, -5.0) as ok:  # type: ignore[arg-type]
        assert ok is True

    assert uses_torch_cuda("  torch\x00 ", "  CUDA:0\x00 ") is True
    assert uses_torch_cuda("sentence-transformers", "cuda") is True
    assert uses_torch_cuda(True, "cuda") is False  # type: ignore[arg-type]
    assert uses_torch_cuda("torch", False) is False  # type: ignore[arg-type]

    owner = _DummyOwner()
    assert is_cuda_model_registered(owner) is False
    model = load_model(owner, uses_cuda=True, factory=lambda: "loaded")
    assert model == "loaded"
    assert is_cuda_model_registered(owner) is True
    assert active_cuda_model_count() >= 1
    release_model(owner, used_cuda=True)
    assert is_cuda_model_registered(owner) is False

    # Non-weakrefable owner (dict) must not raise TypeError
    non_weak_owner = {"name": "dict-owner"}
    assert is_cuda_model_registered(non_weak_owner) is False
    assert load_model(non_weak_owner, uses_cuda=True, factory=lambda: "ok") == "ok"
    assert release_model(non_weak_owner, used_cuda=True) is False


def test_execution_profile_helpers_and_policy_nan_inf_bool_resilience() -> None:
    prof = ExecutionProfile(
        tier="  smart\x00 ",
        num_ctx=16384,
        max_ctx=32768,
        parallel_limit=2,
        think=True,
        prompt_budget_tokens=12000,
    )
    assert prof.tier == "smart"
    assert prof.is_smart_tier() is True
    assert prof.is_background_tier() is False
    assert prof.has_context_headroom() is True
    assert prof.to_dict() == prof.cache_scope()

    policy = ModelExecutionPolicy(
        {
            "models": {
                "fast_code": "qwen2.5-coder:7b",
                "heavy_code": "qwen3.5:9b",
            },
            "model_execution": {
                "smart": {
                    "context_tokens": float("nan"),
                    "large_context_tokens": float("inf"),
                    "max_context_tokens": None,
                    "parallel": False,
                    "context_reserve_tokens": "bad",
                    "thinking_roles": "reasoning",
                }
            },
        }
    )

    p = policy.profile(
        "qwen3.5:9b",
        role="reasoning",
        requested_ctx=float("nan"),  # type: ignore[arg-type]
        input_tokens=float("nan"),  # type: ignore[arg-type]
        output_tokens=float("inf"),  # type: ignore[arg-type]
        vram_free_mb=True,  # type: ignore[arg-type]
    )
    assert p.tier == "smart"
    assert p.num_ctx >= 4096
    assert p.parallel_limit == 1
    assert p.think is True

    # vram_free_mb=True (boolean) must not be treated as 1 MB free VRAM
    clean_payload, applied_prof = policy.apply_payload(
        "qwen3.5:9b",
        {
            "options": {
                "num_ctx": float("nan"),
                "temperature": float("nan"),
            }
        },
        role="reasoning",
        vram_free_mb=True,  # type: ignore[arg-type]
    )
    assert "keep_alive" not in clean_payload
    assert clean_payload["options"]["num_ctx"] == applied_prof.num_ctx
    assert "temperature" not in clean_payload["options"]
