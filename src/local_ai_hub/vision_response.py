"""Pure request and response assembly for vision model calls."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .json_utils import dumps as json_dumps
from .vision_contracts import (
    UNTRUSTED_CONTEXT_INSTRUCTION,
    VISION_MAX_INLINE_RESPONSE_CHARS,
    VISION_MAX_PROMPT_CHARS,
    VISION_MAX_SCHEMA_CHARS,
)


@dataclass(frozen=True)
class VisionRequestBuild:
    payload: dict[str, Any] | None
    prompt_context: str
    error: dict[str, Any] | None = None


def _input_error(message: str, code: str = "vision_input_error") -> dict[str, Any]:
    return {
        "success": False,
        "terminal": True,
        "retryable": False,
        "error": message,
        "error_code": code,
    }


def build_vision_request(
    *,
    model: str,
    prompt: str,
    images: list[str],
    max_tokens: int,
    schema: Any,
    ollama_enabled: bool,
    model_context: Any,
    bundle_context: str,
    image_size: tuple[int, int] | None,
) -> VisionRequestBuild:
    """Validate bounded prompt/schema and assemble the provider request."""
    if isinstance(schema, dict):
        try:
            schema_text = json_dumps(schema, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError, OverflowError):
            return VisionRequestBuild(None, "", _input_error("Vision JSON schema is invalid."))
        if len(schema_text) > VISION_MAX_SCHEMA_CHARS:
            return VisionRequestBuild(
                None,
                "",
                _input_error("Vision JSON schema exceeds the bounded size limit."),
            )

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
        prompt_context += (
            "\n\n"
            + UNTRUSTED_CONTEXT_INSTRUCTION
            + "\nFrontend evidence bundle:\n"
            + json_dumps(model_context.prompt_payload(), ensure_ascii=False)
        )
    elif bundle_context:
        prompt_context += (
            "\n\n"
            + UNTRUSTED_CONTEXT_INSTRUCTION
            + "\nFrontend evidence bundle:\n"
            + bundle_context
        )
    prompt_budget = max(0, VISION_MAX_PROMPT_CHARS - len(prompt_suffix))
    if len(prompt_context) > prompt_budget:
        return VisionRequestBuild(
            None,
            "",
            _input_error(
                "Vision prompt and frontend evidence exceed the bounded prompt limit.",
                "frontend_prompt_too_large",
            ),
        )
    prompt_context += prompt_suffix

    if isinstance(schema, dict):
        output_format: Any = schema
    elif not ollama_enabled:
        output_format = "json"
    else:
        output_format = {
            "type": "object",
            "required": ["summary", "findings", "unknowns", "recommended_checks"],
            "properties": {
                "summary": {"type": "string", "minLength": 1, "pattern": r"\S"},
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": [
                            "id", "severity", "category", "problem", "observed",
                            "hypothesized", "uncertainty", "confidence", "element_ids",
                            "bbox", "evidence", "likely_cause", "fix_hint",
                            "needs_runtime_check", "observation_facts",
                        ],
                        "properties": {
                            "id": {"type": "string", "minLength": 1, "pattern": r"\S"},
                            "severity": {
                                "type": "string",
                                "enum": ["blocker", "high", "medium", "low", "info"],
                            },
                            "category": {
                                "type": "string",
                                "enum": [
                                    "layout", "responsive", "accessibility",
                                    "interaction", "visual-regression", "runtime",
                                ],
                            },
                            "problem": {"type": "string", "minLength": 1, "pattern": r"\S"},
                            "observed": {"type": "string", "minLength": 1, "pattern": r"\S"},
                            "hypothesized": {"type": "string", "minLength": 1, "pattern": r"\S"},
                            "uncertainty": {"type": "array", "items": {"type": "string"}},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "element_ids": {
                                "type": "array",
                                "items": {"type": "string", "minLength": 1, "pattern": r"\S"},
                            },
                            "bbox": {
                                "anyOf": [
                                    {
                                        "type": "array",
                                        "items": {"type": "number"},
                                        "minItems": 4,
                                        "maxItems": 4,
                                    },
                                    {"type": "null"},
                                ],
                            },
                            "evidence": {
                                "type": "array",
                                "items": {"type": "string", "minLength": 1, "pattern": r"\S"},
                                "minItems": 1,
                            },
                            "likely_cause": {"type": "string"},
                            "fix_hint": {"type": "string"},
                            "needs_runtime_check": {"type": "boolean"},
                            "observation_facts": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "required": ["source", "element_id", "field", "value"],
                                    "properties": {
                                        "source": {
                                            "type": "string",
                                            "enum": [
                                                "dom", "accessibility",
                                                "computed_styles", "runtime",
                                            ],
                                        },
                                        "element_id": {
                                            "type": "string", "minLength": 1, "pattern": r"\S",
                                        },
                                        "field": {"type": "string", "minLength": 1, "pattern": r"\S"},
                                        "value": {
                                            "anyOf": [
                                                {"type": "string"},
                                                {"type": "number"},
                                                {"type": "boolean"},
                                            ],
                                        },
                                    },
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "additionalProperties": False,
                    },
                },
                "unknowns": {"type": "array", "items": {"type": "string"}},
                "recommended_checks": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        }

    return VisionRequestBuild(
        {
            "model": model,
            "prompt": prompt_context,
            "images": images,
            "stream": False,
            "format": output_format,
            "options": {"num_predict": max_tokens},
        },
        prompt_context,
    )


def vision_success_payload(
    *,
    model: str,
    raw_output: str,
    parsed: Any,
    prompt_context: str,
    image_artifact_id: str | None,
    bundle_artifact_id: str | None,
    raw_output_artifact_id: str | None,
) -> dict[str, Any]:
    """Assemble the successful public vision response."""
    return {
        "success": True,
        "model": model,
        "response": raw_output[:VISION_MAX_INLINE_RESPONSE_CHARS],
        "review": asdict(parsed),
        "prompt": prompt_context,
        "image_artifact_id": image_artifact_id,
        "bundle_artifact_id": bundle_artifact_id,
        "raw_output_artifact_id": raw_output_artifact_id,
    }
