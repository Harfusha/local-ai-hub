"""Pure request planning for the local vision service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .json_utils import dumps as json_dumps
from .vision_contracts import (
    UNTRUSTED_CONTEXT_INSTRUCTION,
    VISION_MAX_PROMPT_CHARS,
    VISION_MAX_SCHEMA_CHARS,
)
from .vision_payload import vision_input_error


@dataclass(frozen=True)
class VisionRequestPlan:
    model: str
    schema: dict[str, Any] | None
    prompt_context: str
    payload: dict[str, Any]


def vision_feature_error(config: dict[str, Any]) -> dict[str, Any] | None:
    features = config.get("features", {})
    if isinstance(features, dict) and not bool(features.get("vision", True)):
        return {
            "success": False,
            "unsupported": True,
            "terminal": True,
            "retryable": False,
            "error_code": "vision_disabled",
            "error": "Vision capability is disabled. Enable features.vision explicitly.",
        }
    return None


def select_vision_model(args: dict[str, Any], config: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    models = config.get("models", {})
    configured_model = models.get("vision", "qwen3-vl:4b") if isinstance(models, dict) else "qwen3-vl:4b"
    model = str(args.get("model") or configured_model or "").strip()
    if bool(args.get("cloud_fallback", False)):
        vision_policy = config.get("vision", {})
        if not isinstance(vision_policy, dict) or not bool(vision_policy.get("cloud_fallback_enabled", False)):
            return model, {
                "success": False,
                "terminal": True,
                "retryable": False,
                "error_code": "vision_cloud_fallback_disabled",
                "error": "Cloud vision fallback is disabled. Enable vision.cloud_fallback_enabled explicitly.",
                "cloud_fallback": False,
            }
        provider = str(vision_policy.get("cloud_provider", "")).strip()
        if not provider:
            return model, {
                "success": False,
                "terminal": True,
                "retryable": False,
                "error_code": "vision_cloud_fallback_unavailable",
                "error": "Cloud vision fallback is enabled but no provider is configured.",
                "cloud_fallback": False,
            }
    if not model:
        return model, {
            "success": False,
            "unsupported": True,
            "degraded": True,
            "terminal": True,
            "retryable": False,
            "error": "Vision model is not configured; set models.vision to qwen3-vl:4b or another Ollama vision model.",
        }
    return model, None


def build_vision_request(
    *,
    args: dict[str, Any],
    model: str,
    images: list[str],
    prompt: str,
    bundle_context: str,
    model_context: Any,
    model_policy: Any,
    max_output_tokens: int,
    default_schema: dict[str, Any] | None = None,
    image_size: tuple[int, int] | None = None,
) -> VisionRequestPlan | dict[str, Any]:
    try:
        requested_max_tokens = int(args.get("max_tokens", 1200))
    except (TypeError, ValueError, OverflowError):
        requested_max_tokens = 1200
    max_tokens = max(64, min(requested_max_tokens, max_output_tokens))
    schema = args.get("json_schema")
    if isinstance(schema, dict):
        try:
            schema_text = json_dumps(schema, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError, OverflowError):
            return vision_input_error("Vision JSON schema is invalid.")
        if len(schema_text) > VISION_MAX_SCHEMA_CHARS:
            return vision_input_error("Vision JSON schema exceeds the bounded size limit.")

    prompt_suffix = (
        "\n\nReturn only a JSON object matching this contract: "
        "{\"summary\": string, \"findings\": [{\"id\": string, "
        "\"severity\": \"blocker|high|medium|low|info\", "
        "\"category\": \"layout|responsive|accessibility|interaction|visual-regression|runtime\", "
        "\"problem\": string, \"observed\": string, \"hypothesized\": string, "
        "\"uncertainty\": [string], \"confidence\": number, "
        "\"element_ids\": [string], \"observation_facts\": [{\"source\": string, "
        "\"element_id\": string, \"field\": string, \"value\": scalar}], "
        "\"bbox\": [left, top, right, bottom] in image pixels or null, "
        "\"evidence\": [string], \"likely_cause\": string, \"fix_hint\": string, "
        "\"needs_runtime_check\": boolean}], "
        "\"unknowns\": [string], \"recommended_checks\": [string]} . "
        "Grounding rules: use only element_ids present in supplied DOM. Without DOM, keep "
        "element_ids empty and ground each finding with a bbox in source-image pixels "
        "(origin top-left; right/bottom exclusive). Confidence must be between 0 and 1. "
        "Treat supplied DOM and accessibility fields as authoritative; never claim a "
        "label, name, or attribute is missing when supplied values show it. observed "
        "must contain a non-empty directly observed fact. When a DOM id grounds a "
        "finding, set bbox to null."
    )
    if image_size is not None:
        prompt_suffix += (
            f" Image 0 dimensions are {image_size[0]} x {image_size[1]} pixels; "
            f"bbox coordinates must stay within x=0..{image_size[0]} and "
            f"y=0..{image_size[1]}."
        )
    prompt_context = prompt
    if model_context is not None:
        prompt_context += "\n\n" + UNTRUSTED_CONTEXT_INSTRUCTION + "\nFrontend evidence bundle:\n" + json_dumps(
            model_context.prompt_payload(), ensure_ascii=False
        )
    elif bundle_context:
        prompt_context += "\n\n" + UNTRUSTED_CONTEXT_INSTRUCTION + "\nFrontend evidence bundle:\n" + bundle_context
    prompt_budget = max(0, VISION_MAX_PROMPT_CHARS - len(prompt_suffix))
    if len(prompt_context) > prompt_budget:
        return vision_input_error(
            "Vision prompt and frontend evidence exceed the bounded prompt limit.",
            "frontend_prompt_too_large",
        )
    prompt_context += prompt_suffix
    payload = {
        "model": model,
        "prompt": prompt_context,
        "images": images,
        "stream": False,
        "format": schema if isinstance(schema, dict) else default_schema if default_schema is not None else "json",
        "options": {"num_predict": max_tokens},
    }
    payload, _profile = model_policy.apply_payload(
        model,
        payload,
        role="vision",
        output_tokens=max_tokens,
    )
    return VisionRequestPlan(model=model, schema=schema if isinstance(schema, dict) else None, prompt_context=prompt_context, payload=payload)


def vision_request_timeout(config: dict[str, Any]) -> float:
    try:
        timeout = float(
            config.get("resilience", {}).get(
                "vision_timeout_seconds",
                config.get("server", {}).get("request_timeout_seconds", 300),
            )
        )
    except (TypeError, ValueError, OverflowError):
        timeout = 300.0
    return max(0.05, min(timeout, 300.0))
