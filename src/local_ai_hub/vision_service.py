"""Orchestration for local vision requests."""

from __future__ import annotations

import base64
import threading
from dataclasses import asdict
from typing import Any

from .frontend_review import build_coder_context, compare_screens
from .vision_contracts import (
    VISION_MAX_RUNTIME_OUTPUT_CHARS,
    bound_vision_result,
    parse_vision_result,
)
from .vision_inputs import _retired_field_error, prepare_vision_inputs
from .vision_payload import vision_success_payload
from .vision_request import build_vision_request, select_vision_model, vision_request_timeout
from .vision_runtime import vision_capability_error, vision_generation_error


class VisionService:
    """Coordinate existing vision phases using explicit service dependencies."""

    def __init__(
        self,
        *,
        config: dict[str, Any] | None,
        runtime: Any,
        artifacts: Any,
        model_policy: Any,
        repo_tools: Any,
        max_output_tokens: int,
    ) -> None:
        self.config = config if isinstance(config, dict) else {}
        self.runtime = runtime
        self.artifacts = artifacts
        self.model_policy = model_policy
        self.repo_tools = repo_tools
        if isinstance(max_output_tokens, bool) or not isinstance(max_output_tokens, (int, float)):
            tokens = 1200
        else:
            try:
                import math
                tokens = int(max_output_tokens) if math.isfinite(max_output_tokens) else 1200
            except Exception:
                tokens = 1200
        self.max_output_tokens = max(64, tokens)

    def is_vision_enabled(self) -> bool:
        features = self.config.get("features", {})
        if isinstance(features, dict):
            return bool(features.get("vision", True))
        return True

    def configured_vision_model(self) -> str:
        models = self.config.get("models", {})
        if isinstance(models, dict):
            return str(models.get("vision", "qwen3-vl:4b") or "qwen3-vl:4b").strip()
        return "qwen3-vl:4b"

    @staticmethod
    def cancelled_result(model_name: str = "") -> dict[str, Any]:
        result: dict[str, Any] = {
            "success": False,
            "reason": "cancelled",
            "cancelled": True,
            "terminal": True,
            "retryable": False,
            "error_code": "cancelled",
            "error": "Vision request was cancelled.",
        }
        clean_model = str(model_name or "").replace("\x00", "").strip()
        if clean_model:
            result["model"] = clean_model
        return result

    @staticmethod
    def default_schema() -> dict[str, Any]:
        return {
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
                            "element_ids": {"type": "array", "items": {"type": "string", "minLength": 1, "pattern": r"\S"}},
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
                            "evidence": {"type": "array", "items": {"type": "string", "minLength": 1, "pattern": r"\S"}, "minItems": 1},
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
                                        "element_id": {"type": "string", "minLength": 1, "pattern": r"\S"},
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

    def _compare_artifacts(
        self, args: dict[str, Any], cancel_event: threading.Event | None
    ) -> dict[str, Any]:
        if args.get("cloud_fallback"):
            return {"success": False, "terminal": True, "retryable": False,
                    "error_code": "visual_comparison_local_only",
                    "error": "Screenshot comparison uses the configured local vision model only"}
        screenshots: list[bytes] = []
        for reference in (
            args.get("baseline_screenshot_artifact_id"),
            args.get("screenshot_artifact_id") or args.get("image_artifact_id"),
        ):
            if not isinstance(reference, str) or not reference.strip():
                return {"success": False, "terminal": True, "retryable": False,
                        "error_code": "visual_comparison_input_invalid",
                        "error": "Comparison requires baseline and candidate screenshot artifact IDs"}
            prepared = prepare_vision_inputs(
                args={"image_artifact_id": reference}, image_path="", prompt="Compare screenshots",
                artifacts=self.artifacts,
            )
            if isinstance(prepared, dict):
                return prepared
            screenshots.append(base64.b64decode(prepared.images[0], validate=True))

        def review(comparison_args: dict[str, Any]) -> dict[str, Any]:
            inherited = {key: args[key] for key in ("model", "max_tokens", "root", "cloud_fallback") if key in args}
            return self.run({**inherited, **comparison_args}, cancel_event=cancel_event)

        return compare_screens(screenshots[0], screenshots[1], review=review)

    def run(
        self,
        args: dict[str, Any],
        *,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Run vision phases while preserving their established order and contracts."""
        features = self.config.get("features", {})
        if isinstance(features, dict) and not bool(features.get("vision", True)):
            return {
                "success": False,
                "unsupported": True,
                "terminal": True,
                "retryable": False,
                "error_code": "vision_disabled",
                "error": "Vision capability is disabled. Enable features.vision explicitly.",
            }

        def is_cancelled() -> bool:
            return cancel_event is not None and cancel_event.is_set()

        if is_cancelled():
            return self.cancelled_result()
        if not isinstance(args, dict):
            return {
                "success": False,
                "terminal": True,
                "retryable": False,
                "error_code": "invalid_request",
                "error": "Vision request must be an object.",
            }
        field_error = _retired_field_error(args)
        if field_error:
            return {
                "success": False,
                "terminal": True,
                "retryable": False,
                "error_code": "invalid_request",
                "error": field_error,
            }
        if args.get("baseline_screenshot_artifact_id"):
            return self._compare_artifacts(args, cancel_event)
        image_path = str(args.get("image", args.get("image_path", "")))
        prompt = str(args.get("prompt", args.get("task", "Describe this image in detail.")))
        model, model_error = select_vision_model(args, self.config)
        if model_error:
            return model_error

        prepared_inputs = prepare_vision_inputs(
            args=args,
            image_path=image_path,
            prompt=prompt,
            artifacts=self.artifacts,
        )
        if isinstance(prepared_inputs, dict):
            return prepared_inputs
        images = prepared_inputs.images
        image_artifact_id = prepared_inputs.image_artifact_id
        bundle_artifact_id = prepared_inputs.bundle_artifact_id
        bundle_context = prepared_inputs.bundle_context
        frontend_bundle = prepared_inputs.frontend_bundle
        model_context = prepared_inputs.model_context
        image_size = prepared_inputs.image_size

        request_plan = build_vision_request(
            args=args,
            model=model,
            images=images,
            prompt=prompt,
            bundle_context=bundle_context,
            model_context=model_context,
            model_policy=self.model_policy,
            max_output_tokens=self.max_output_tokens,
            default_schema=(self.default_schema() if bool(self.config.get("ollama", {}).get("enabled", False)) else None),
            image_size=image_size,
        )
        if isinstance(request_plan, dict):
            return request_plan
        payload = request_plan.payload
        prompt_context = request_plan.prompt_context
        schema = request_plan.schema
        timeout = vision_request_timeout(self.config)
        try:
            if is_cancelled():
                return self.cancelled_result(model)
            capability_response = self.runtime.request(
                "/api/show",
                {"name": model},
                timeout=min(timeout, 1.0),
            )
            capability_error = vision_capability_error(capability_response, model)
            if is_cancelled():
                return self.cancelled_result(model)
            if capability_error:
                return capability_error
            if cancel_event is not None:
                interruptible = getattr(self.runtime, "request_interruptible", None)
                if not callable(interruptible):
                    return {"success": False, "unsupported": True, "terminal": True, "retryable": False,
                            "error": "Vision runtime does not support request cancellation.", "model": model}
                res = interruptible("/api/generate", payload, should_stop=cancel_event.is_set, timeout=timeout)
            else:
                res = self.runtime.request("/api/generate", payload, timeout=timeout)
            if is_cancelled():
                return self.cancelled_result(model)
            generation_error = vision_generation_error(res, model)
            if generation_error:
                return generation_error
            raw_output = res.get("response", "")
            if len(raw_output) > VISION_MAX_RUNTIME_OUTPUT_CHARS:
                raw_artifact_id = ""
                try:
                    raw_artifact_id = str(self.artifacts.put(raw_output[:VISION_MAX_RUNTIME_OUTPUT_CHARS], kind="vision-output"))
                except Exception:
                    pass
                return {
                    "success": False,
                    "model": model,
                    "terminal": True,
                    "retryable": False,
                    "error": "Vision runtime output exceeds the bounded response limit.",
                    "raw_output_artifact_id": raw_artifact_id,
                }
            raw_artifact_id = ""
            try:
                raw_artifact_id = str(self.artifacts.put(raw_output, kind="vision-output"))
            except Exception:
                pass
            dom_context = model_context.dom if model_context is not None else {}
            dom_elements = dom_context.get("elements", []) if isinstance(dom_context, dict) else []
            valid_element_ids = {
                str(element["element_id"])
                for element in dom_elements
                if isinstance(element, dict)
                and isinstance(element.get("element_id"), (str, int, float))
                and not isinstance(element.get("element_id"), bool)
                and str(element["element_id"])
            } if isinstance(dom_elements, list) else set()
            parsed = parse_vision_result(
                raw_output,
                strict_output_shape=bool(
                    self.config.get("ollama", {}).get("enabled", False)
                    and not isinstance(schema, dict)
                ),
                require_observation_fields=model_context is not None,
                valid_element_ids=valid_element_ids,
                observation_sources=(
                    model_context.observation_sources if model_context is not None else None
                ),
                image_size=image_size,
            )
            if parsed.terminal:
                return {
                    "success": False,
                    "degraded": True,
                    "model": model,
                    "terminal": True,
                    "retryable": False,
                    "error": parsed.error or {"code": "malformed_vision_output", "message": "Vision output is invalid."},
                    "error_code": "vision_output_invalid",
                    "raw_output_artifact_id": raw_artifact_id,
                }
            parsed = bound_vision_result(parsed)
            result = vision_success_payload(
                model=model,
                raw_output=raw_output,
                parsed=parsed,
                prompt_context=prompt_context,
                image_artifact_id=image_artifact_id,
                bundle_artifact_id=bundle_artifact_id,
                raw_output_artifact_id=raw_artifact_id,
            )
            if frontend_bundle:
                repo_context = None
                root = str(args.get("root") or "").strip()
                fix_requested = any(
                    marker in prompt.lower()
                    for marker in ("fix", "repair", "implement", "change", "correct")
                )
                if root and fix_requested and self.repo_tools is not None:
                    findings = asdict(parsed).get("findings", [])
                    query = " ".join(
                        [
                            prompt,
                            *[str(item.get("finding_id", "")) for item in findings],
                            *[str(element_id) for item in findings for element_id in item.get("element_ids", [])],
                            *[str(item.get("fix_hint", "")) for item in findings],
                        ]
                    ).strip()
                    try:
                        context_result = self.repo_tools.context_pack(root, query, max_tokens=2600)
                        if isinstance(context_result, dict) and context_result.get("success", True):
                            repo_context = context_result
                    except Exception:
                        repo_context = None
                coder_context = build_coder_context(
                    asdict(parsed), frontend_bundle, repo_context=repo_context
                )
                if coder_context.get("terminal"):
                    return {
                        "success": False,
                        "model": model,
                        "terminal": True,
                        "retryable": False,
                        "error": coder_context.get("error", {}).get("message", "Invalid coder context"),
                        "error_code": coder_context.get("error", {}).get("code", "invalid_coder_context"),
                    }
                result["coder_context"] = coder_context
            return result
        except Exception as exc:
            if is_cancelled():
                return self.cancelled_result(model)
            detail = str(exc).lower()
            transient = isinstance(exc, (TimeoutError, ConnectionError, OSError)) or any(
                marker in detail for marker in ("timeout", "timed out", "connection", "network", "handoff", "temporarily", "unavailable")
            )
            return {
                "success": False,
                "model": model,
                "terminal": not transient,
                "retryable": transient,
                "error": "Vision service temporarily unavailable; retry the request." if transient else "Vision runtime failed; inspect the configured local backend and vision model.",
            }
