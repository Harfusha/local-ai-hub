"""Response payload construction for the local vision service."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .vision_contracts import VISION_MAX_INLINE_RESPONSE_CHARS


def vision_input_error(message: str, code: str = "vision_input_error") -> dict[str, Any]:
    """Build the terminal, non-retryable response for invalid vision input."""
    return {
        "success": False,
        "terminal": True,
        "retryable": False,
        "error": str(message or "") if message is not None else "",
        "error_code": str(code or "vision_input_error"),
    }


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
    """Assemble the successful vision response without provider side effects."""
    raw = str(raw_output or "") if raw_output is not None else ""
    review_data = asdict(parsed) if hasattr(parsed, "__dataclass_fields__") else (parsed if isinstance(parsed, dict) else {})
    return {
        "success": True,
        "model": str(model or ""),
        "response": raw[:VISION_MAX_INLINE_RESPONSE_CHARS],
        "review": review_data,
        "prompt": str(prompt_context or ""),
        "image_artifact_id": image_artifact_id,
        "bundle_artifact_id": bundle_artifact_id,
        "raw_output_artifact_id": raw_output_artifact_id,
    }
