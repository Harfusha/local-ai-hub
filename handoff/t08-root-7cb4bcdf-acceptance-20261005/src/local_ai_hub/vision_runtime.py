"""Pure classification for vision runtime responses."""

from __future__ import annotations

from typing import Any


_TRANSIENT_MARKERS = (
    "timeout", "timed out", "connection", "network", "handoff",
    "temporarily", "unavailable", "try again", "http 429", "http 502", "http 503",
)


def _transient(error_text: str) -> bool:
    return any(marker in error_text for marker in _TRANSIENT_MARKERS)


def vision_capability_error(response: Any, model: str) -> dict[str, Any] | None:
    if not isinstance(response, dict):
        return {
            "success": False,
            "model": model,
            "terminal": True,
            "retryable": False,
            "error": "Vision model capability preflight returned an invalid response.",
        }
    if response.get("error"):
        capability_error = str(response.get("error", "")).lower()
        missing_model = (
            "model not found" in capability_error
            or "no such model" in capability_error
            or ("not found" in capability_error and "model" in capability_error)
        )
        transient = _transient(capability_error)
        if missing_model:
            return {
                "success": False,
                "model": model,
                "unsupported": True,
                "degraded": True,
                "terminal": True,
                "retryable": False,
                "error": f"Vision model '{model}' is unavailable. Configure an existing vision-capable local backend and models.vision; no runtime is installed automatically.",
                "error_code": "vision_model_missing",
            }
        return {
            "success": False,
            "model": model,
            "terminal": not transient,
            "retryable": transient,
            "error": "Vision service temporarily unavailable; retry the request." if transient else "Vision model capability preflight failed; inspect the configured local backend and vision model.",
            "error_code": "vision_preflight_failed",
        }
    capability_values: list[str] = []
    for value in response.get("capabilities", []):
        capability_values.append(str(value).lower())
    details = response.get("details")
    if isinstance(details, dict):
        for key in ("family", "families"):
            values = details.get(key, [])
            if isinstance(values, list):
                capability_values.extend(str(value).lower() for value in values)
            elif values:
                capability_values.append(str(values).lower())
    supports_vision = any(
        marker in value
        for value in capability_values
        for marker in ("vision", "image", "multimodal", "clip", "vl")
    )
    if not supports_vision:
        return {
            "success": False,
            "model": model,
            "unsupported": True,
            "degraded": True,
            "terminal": True,
            "retryable": False,
            "error": f"Vision model '{model}' does not advertise image or multimodal capability; choose a configured vision-capable local model.",
            "error_code": "vision_model_unsupported",
        }
    return None


def vision_generation_error(response: Any, model: str) -> dict[str, Any] | None:
    if not isinstance(response, dict):
        return {
            "success": False,
            "model": model,
            "terminal": True,
            "retryable": False,
            "error": "Vision runtime returned an invalid response.",
        }
    if response.get("error"):
        error_text = str(response.get("error", "")).lower()
        missing_model = (
            "model not found" in error_text
            or "no such model" in error_text
            or ("not found" in error_text and "model" in error_text)
        )
        if missing_model:
            return {
                "success": False,
                "model": model,
                "unsupported": True,
                "degraded": True,
                "terminal": True,
                "retryable": False,
                "error": f"Vision model '{model}' is unavailable. Configure an existing vision-capable local backend and models.vision; no runtime is installed automatically.",
            }
        transient = _transient(error_text)
        return {
            "success": False,
            "model": model,
            "terminal": not transient,
            "retryable": transient,
            "error": "Vision service temporarily unavailable; retry the request." if transient else "Vision runtime returned an error; inspect the configured local backend and vision model.",
        }
    if not isinstance(response.get("response", ""), str):
        return {
            "success": False,
            "model": model,
            "terminal": True,
            "retryable": False,
            "error": "Vision runtime returned an invalid response.",
        }
    return None
