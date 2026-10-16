from __future__ import annotations

import pytest

from local_ai_hub.vision_runtime import (
    _transient,
    is_transient_vision_error,
    is_vision_model_missing_error,
    vision_capability_error,
    vision_generation_error,
)
from local_ai_hub.vision_service import VisionService


def test_vision_runtime_transient_and_error_helpers() -> None:
    # Non-string input to _transient must not raise AttributeError
    assert _transient(None) is False  # type: ignore[arg-type]
    assert _transient(123) is False  # type: ignore[arg-type]
    assert _transient("") is False

    # is_transient_vision_error helper
    assert is_transient_vision_error("Connection timeout while reading") is True
    assert is_transient_vision_error("HTTP 503 Service Unavailable") is True
    assert is_transient_vision_error("Permanent invalid syntax") is False
    assert is_transient_vision_error(None) is False
    assert is_transient_vision_error(42) is False

    # is_vision_model_missing_error helper
    assert is_vision_model_missing_error("model not found: qwen3-vl:4b") is True
    assert is_vision_model_missing_error("no such model") is True
    assert is_vision_model_missing_error("out of memory") is False
    assert is_vision_model_missing_error(None) is False


def test_vision_runtime_error_classifiers_model_sanitization() -> None:
    # Null bytes in model name
    cap_err = vision_capability_error(None, "qwen3-vl:4b\x00")
    assert cap_err is not None
    assert "\x00" not in cap_err["model"]
    assert cap_err["model"] == "qwen3-vl:4b"

    gen_err = vision_generation_error(None, "qwen3-vl:4b\x00")
    assert gen_err is not None
    assert "\x00" not in gen_err["model"]
    assert gen_err["model"] == "qwen3-vl:4b"


def test_vision_service_init_and_inspection_helpers() -> None:
    # None config and malformed tokens
    service = VisionService(
        config=None,  # type: ignore[arg-type]
        runtime=object(),
        artifacts=object(),
        model_policy=object(),
        repo_tools=object(),
        max_output_tokens=float("nan"),  # type: ignore[arg-type]
    )
    assert service.is_vision_enabled() is True
    assert service.configured_vision_model() == "qwen3-vl:4b"
    assert service.max_output_tokens >= 64

    # Cancelled result sanitization
    cancelled = VisionService.cancelled_result("test_model\x00")
    assert cancelled["cancelled"] is True
    assert "\x00" not in cancelled["model"]
    assert cancelled["model"] == "test_model"
