from __future__ import annotations

from typing import Any

from local_ai_hub.vision_contracts import VISION_MAX_PROMPT_CHARS
from local_ai_hub.vision_request import (
    build_vision_request,
    select_vision_model,
    vision_feature_error,
    vision_request_timeout,
)
from local_ai_hub.vision_runtime import vision_capability_error, vision_generation_error


class _ModelPolicy:
    def __init__(self) -> None:
        self.call: tuple[str, dict[str, Any], dict[str, Any]] | None = None

    def apply_payload(self, model: str, payload: dict[str, Any], **kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        self.call = (model, payload, kwargs)
        return payload, {"role": kwargs["role"]}


def test_vision_model_selection_preserves_disabled_cloud_and_missing_errors() -> None:
    assert vision_feature_error({"features": {"vision": False}}) == {
        "success": False,
        "unsupported": True,
        "terminal": True,
        "retryable": False,
        "error_code": "vision_disabled",
        "error": "Vision capability is disabled. Enable features.vision explicitly.",
    }
    _, cloud_error = select_vision_model({"cloud_fallback": True}, {"models": {"vision": "vl"}})
    assert cloud_error is not None
    assert cloud_error["error_code"] == "vision_cloud_fallback_disabled"
    _, missing_error = select_vision_model({}, {"models": {"vision": ""}})
    assert missing_error is not None
    assert missing_error["error"] == (
        "Vision model is not configured; set models.vision to qwen3-vl:4b or another Ollama vision model."
    )


def test_vision_request_plan_preserves_multimodal_payload_and_token_clamp() -> None:
    policy = _ModelPolicy()
    schema = {"type": "object", "required": ["summary"]}
    plan = build_vision_request(
        args={"max_tokens": 500, "json_schema": schema},
        model="local-vl",
        images=["cG5n"],
        prompt="Review image",
        bundle_context="",
        model_context=None,
        model_policy=policy,
        max_output_tokens=128,
    )
    assert not isinstance(plan, dict)
    assert plan.model == "local-vl"
    assert plan.payload == {
        "model": "local-vl",
        "prompt": plan.prompt_context,
        "images": ["cG5n"],
        "stream": False,
        "format": schema,
        "options": {"num_predict": 128},
    }
    assert plan.prompt_context.startswith("Review image\n\nReturn only a JSON object")
    assert policy.call is not None
    assert policy.call[0] == "local-vl"
    assert policy.call[2] == {"role": "vision", "output_tokens": 128}
    assert plan.payload["format"] == schema


def test_vision_request_plan_returns_existing_prompt_bound_error() -> None:
    plan = build_vision_request(
        args={},
        model="local-vl",
        images=["cG5n"],
        prompt="x" * VISION_MAX_PROMPT_CHARS,
        bundle_context="",
        model_context=None,
        model_policy=_ModelPolicy(),
        max_output_tokens=1200,
    )
    assert isinstance(plan, dict)
    assert plan["error_code"] == "frontend_prompt_too_large"
    assert plan["terminal"] is True
    assert plan["retryable"] is False


def test_vision_runtime_classifiers_preserve_capability_and_retry_contracts() -> None:
    assert vision_capability_error({"capabilities": ["image"]}, "local-vl") is None
    unsupported = vision_capability_error({"capabilities": ["completion"]}, "local-vl")
    assert unsupported is not None
    assert unsupported["error_code"] == "vision_model_unsupported"
    transient = vision_capability_error({"error": "connection timeout"}, "local-vl")
    assert transient is not None
    assert transient["error_code"] == "vision_preflight_failed"
    assert transient["terminal"] is False
    assert transient["retryable"] is True
    malformed = vision_generation_error({"response": None}, "local-vl")
    assert malformed is not None
    assert malformed == {
        "success": False,
        "model": "local-vl",
        "terminal": True,
        "retryable": False,
        "error": "Vision runtime returned an invalid response.",
    }


def test_vision_timeout_keeps_default_and_bounds() -> None:
    assert vision_request_timeout({}) == 300.0
    assert vision_request_timeout({"resilience": {"vision_timeout_seconds": 0}}) == 0.05
    assert vision_request_timeout({"resilience": {"vision_timeout_seconds": 900}}) == 300.0
