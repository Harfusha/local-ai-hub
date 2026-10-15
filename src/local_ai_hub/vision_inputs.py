"""Input and frontend-evidence preparation for vision requests."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .frontend_review import FrontendReviewError, build_model_context, parse_bounded_context
from .json_utils import dumps as json_dumps
from .vision_contracts import (
    VISION_MAX_BUNDLE_CHARS,
    VISION_MAX_IMAGE_BYTES,
    VISION_MAX_IMAGE_CHARS,
    image_dimensions,
)


@dataclass(frozen=True)
class VisionInputs:
    images: list[str]
    image_artifact_id: str
    bundle_artifact_id: str
    bundle_context: str
    frontend_bundle: dict[str, Any]
    model_context: Any
    image_size: tuple[int, int] | None


def prepare_vision_inputs(
    *,
    args: dict[str, Any],
    image_path: str,
    prompt: str,
    tenant: str,
    artifacts: Any,
) -> VisionInputs | dict[str, Any]:
    """Resolve bounded image/artifact inputs and construct grounded UI context."""
    def input_error(message: str, code: str = "vision_input_error") -> dict[str, Any]:
        return {
            "success": False,
            "terminal": True,
            "retryable": False,
            "error": message,
            "error_code": code,
        }

    images: list[str] = []

    def append_image(value: str) -> dict[str, Any] | None:
        if len(value) > VISION_MAX_IMAGE_CHARS:
            return input_error(
                "Vision image transport exceeds the bounded character limit.",
                "vision_image_transport_too_large",
            )
        encoded = value
        if value.startswith("data:image/"):
            if "," not in value:
                return input_error("Vision image data URL is invalid.", "vision_image_integrity")
            encoded = value.split(",", 1)[1]
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            return input_error("Vision image input is not valid base64.", "vision_image_integrity")
        if len(decoded) > VISION_MAX_IMAGE_BYTES:
            return input_error(
                "Vision image exceeds the bounded decoded-byte limit.",
                "vision_image_too_large",
            )
        # Ollama expects the raw base64 payload, not the transport prefix
        # from a browser-style data URL. Keep validation accepting both,
        # but normalize the provider payload to one canonical form.
        images.append(encoded)
        return None

    def is_inline_image(value: str) -> bool:
        if value.startswith("data:image/"):
            return True
        try:
            return bool(value) and bool(base64.b64decode(value, validate=True))
        except (ValueError, TypeError):
            return False

    if image_path:
        if (
            "image_path" not in args
            and (image_path.startswith("data:image/") or len(image_path) > VISION_MAX_IMAGE_CHARS or is_inline_image(image_path))
        ):
            error = append_image(image_path)
            if error:
                return error
        else:
            try:
                p = Path(image_path)
                is_file = p.is_file()
            except (OSError, ValueError):
                return input_error("Vision image path could not be inspected; provide a readable image or base64 data.")
            if not is_file:
                return input_error("Vision image path was not found; provide a readable image or base64 data.")
            try:
                size_bytes = int(p.stat().st_size)
                encoded_chars = ((size_bytes + 2) // 3) * 4
                if size_bytes > VISION_MAX_IMAGE_BYTES:
                    return input_error("Vision image exceeds the bounded decoded-byte limit.", "vision_image_too_large")
                if encoded_chars > VISION_MAX_IMAGE_CHARS:
                    return input_error("Vision image transport exceeds the bounded character limit.", "vision_image_transport_too_large")
                b64 = base64.b64encode(p.read_bytes()).decode("utf-8")
                error = append_image(b64)
                if error:
                    return error
            except (OSError, ValueError):
                return input_error("Failed to read image file; verify the path and permissions.")

    image_artifact_id = str(
        args.get("image_artifact_id") or args.get("screenshot_artifact_id") or ""
    ).strip()
    bundle_artifact_id = str(
        args.get("bundle_artifact_id") or args.get("frontend_bundle_artifact_id") or ""
    ).strip()
    direct_context_refs = {
        "dom": str(args.get("dom_artifact_id") or args.get("html_artifact_id") or "").strip(),
        "accessibility": str(
            args.get("accessibility_artifact_id") or args.get("a11y_artifact_id") or ""
        ).strip(),
        "computed_styles": str(
            args.get("computed_styles_artifact_id") or args.get("computed_style_artifact_id") or ""
        ).strip(),
        "runtime": str(
            args.get("runtime_artifact_id") or args.get("runtime_context_artifact_id") or ""
        ).strip(),
    }
    network_artifact_id = str(args.get("network_artifact_id") or "").strip()

    def resolve_artifact(artifact_id: str, max_chars: int) -> tuple[str, dict[str, Any] | None]:
        try:
            artifact = artifacts.get(artifact_id, max_chars=max_chars, tenant=tenant)
        except Exception:
            return "", {
                "success": False,
                "terminal": False,
                "retryable": True,
                "error": "Vision artifact store is unavailable; retry the request.",
            }
        if not isinstance(artifact, dict) or not artifact.get("success"):
            detail = str(artifact.get("error", "")).lower() if isinstance(artifact, dict) else ""
            if any(marker in detail for marker in ("not found", "expired", "missing")):
                return "", input_error("Vision artifact was not found or has expired.")
            return "", {
                "success": False,
                "terminal": False,
                "retryable": True,
                "error": "Vision artifact store returned an error; retry the request.",
            }
        text = artifact.get("text")
        if not isinstance(text, str) or not text:
            return "", input_error("Vision artifact does not contain usable content.")
        try:
            total_chars = int(artifact.get("total_chars", len(text)))
        except (TypeError, ValueError, OverflowError):
            return "", input_error("Vision artifact metadata is invalid.")
        if artifact.get("next_offset") is not None or total_chars > len(text):
            return "", input_error(
                "Vision artifact is truncated; provide the complete artifact.",
                "vision_artifact_truncated",
            )
        if total_chars > max_chars:
            return "", input_error(
                "Vision artifact exceeds the bounded size limit.",
                "vision_artifact_too_large",
            )
        return text[:max_chars], None

    def resolve_binary_artifact(artifact_id: str, max_bytes: int) -> tuple[str, dict[str, Any] | None]:
        try:
            artifact = artifacts.get_binary(artifact_id, tenant=tenant)
        except Exception:
            return "", {
                "success": False,
                "terminal": False,
                "retryable": True,
                "error": "Vision artifact store is unavailable; retry the request.",
            }
        if not isinstance(artifact, dict) or not artifact.get("success"):
            detail = str(artifact.get("error", "")).lower() if isinstance(artifact, dict) else ""
            if any(marker in detail for marker in ("not found", "expired", "missing")):
                return "", input_error("Vision artifact was not found or has expired.")
            return "", input_error("Vision image artifact failed integrity validation.", "vision_artifact_integrity")
        mime_type = str(artifact.get("mime_type", ""))
        encoded = artifact.get("data_base64")
        try:
            size_bytes = int(artifact.get("size_bytes", -1))
        except (TypeError, ValueError, OverflowError):
            size_bytes = -1
        if not mime_type.startswith("image/") or not isinstance(encoded, str) or size_bytes < 0:
            return "", input_error("Vision image artifact exceeds the bounded integrity contract.", "vision_artifact_integrity")
        if len(encoded) > VISION_MAX_IMAGE_CHARS:
            return "", input_error(
                "Vision image transport exceeds the bounded character limit.",
                "vision_image_transport_too_large",
            )
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            return "", input_error("Vision image artifact is not valid base64.", "vision_artifact_integrity")
        if len(decoded) > max_bytes:
            return "", input_error(
                "Vision image exceeds the bounded decoded-byte limit.",
                "vision_image_too_large",
            )
        if len(decoded) != size_bytes:
            return "", input_error("Vision image artifact is truncated or incomplete.", "vision_artifact_truncated")
        return encoded, None

    def resolve_bundle_context(raw: str) -> tuple[str, dict[str, Any] | None]:
        nonlocal image_artifact_id
        if not raw.lstrip().startswith(("{", "[")):
            return raw, None
        try:
            bundle = parse_bounded_context(raw, "frontend_bundle")
        except FrontendReviewError as exc:
            if exc.code == "invalid_frontend_context":
                return "", input_error(
                    "Vision frontend bundle is not valid JSON.",
                    "vision_bundle_invalid",
                )
            return "", exc.as_result()
        resolved = dict(bundle)
        screenshot = resolved.get("screenshot")
        screenshot_ref = screenshot.get("artifact_id", "") if isinstance(screenshot, dict) else ""
        if screenshot_ref and not images:
            image_data, error = resolve_binary_artifact(str(screenshot_ref), VISION_MAX_IMAGE_BYTES)
            if error:
                return "", error
            error = append_image(image_data)
            if error:
                return "", error
            image_artifact_id = str(screenshot_ref)
        for field_name in ("dom", "accessibility", "computed_styles", "runtime"):
            value = resolved.get(field_name)
            if field_name == "runtime":
                runtime_refs: dict[str, str] = {}
                if isinstance(value, dict):
                    for ref_key in ("artifact_id", "console_artifact_id", "network_artifact_id"):
                        ref = str(value.get(ref_key, "")).strip()
                        if ref:
                            runtime_refs[ref_key] = ref
                for ref_key in ("runtime_artifact_id", "network_artifact_id"):
                    ref = str(resolved.get(ref_key, "")).strip()
                    if ref:
                        runtime_refs.setdefault(
                            "console_artifact_id" if ref_key == "runtime_artifact_id" else ref_key,
                            ref,
                        )
                if runtime_refs:
                    runtime_value = dict(value) if isinstance(value, dict) else {}
                    for ref_key, ref in runtime_refs.items():
                        content, error = resolve_artifact(ref, VISION_MAX_BUNDLE_CHARS)
                        if error:
                            return "", error
                        content_key = {
                            "artifact_id": "content",
                            "console_artifact_id": "console_content",
                            "network_artifact_id": "network_content",
                        }[ref_key]
                        runtime_value[content_key] = content
                    resolved[field_name] = runtime_value
                continue
            reference = value.get("artifact_id", "") if isinstance(value, dict) else ""
            if not reference:
                reference = resolved.get(f"{field_name}_artifact_id", "")
            if not reference:
                continue
            content, error = resolve_artifact(str(reference), VISION_MAX_BUNDLE_CHARS)
            if error:
                return "", error
            if isinstance(value, dict):
                resolved[field_name] = {**value, "content": content}
            else:
                resolved[field_name] = {"artifact_id": str(reference), "content": content}
        return json_dumps(resolved, ensure_ascii=False), None

    if image_artifact_id and not images:
        artifact_data, error = resolve_binary_artifact(image_artifact_id, VISION_MAX_IMAGE_BYTES)
        if error:
            return error
        error = append_image(artifact_data)
        if error:
            return error

    comparison_image = args.get("comparison_image")
    if comparison_image is not None:
        if not isinstance(comparison_image, str) or not comparison_image or len(images) != 1:
            return input_error("Visual comparison requires exactly two image inputs.")
        error = append_image(comparison_image)
        if error:
            return error

    bundle_context = ""
    if bundle_artifact_id:
        bundle_context, error = resolve_artifact(bundle_artifact_id, VISION_MAX_BUNDLE_CHARS)
        if error:
            return error
        bundle_context, error = resolve_bundle_context(bundle_context)
        if error:
            return error

    def parse_context_value(field_name: str, value: Any) -> Any:
        return parse_bounded_context(value, field_name)

    frontend_bundle: dict[str, Any] = {}
    if bundle_context:
        if not bundle_context.lstrip().startswith(("{", "[")):
            frontend_bundle = {}
        else:
            try:
                frontend_bundle = parse_bounded_context(bundle_context, "frontend_bundle")
            except FrontendReviewError as exc:
                if exc.code == "invalid_frontend_context":
                    return input_error(
                        "Vision frontend bundle is not valid JSON.",
                        "vision_bundle_invalid",
                    )
                return exc.as_result()
            frontend_bundle["bundle_artifact_id"] = bundle_artifact_id

    inline_bundle = args.get("bundle") or args.get("frontend_bundle") or args.get("dom_bundle")
    if inline_bundle is not None:
        try:
            decoded_inline = (
                parse_context_value("bundle", inline_bundle)
                if not isinstance(inline_bundle, dict)
                else dict(inline_bundle)
            )
        except FrontendReviewError as exc:
            return exc.as_result()
        frontend_bundle.update(decoded_inline)

    for field_name, artifact_id in direct_context_refs.items():
        if not artifact_id:
            continue
        content, error = resolve_artifact(artifact_id, VISION_MAX_BUNDLE_CHARS)
        if error:
            return error
        try:
            context_value = parse_context_value(field_name, content)
        except FrontendReviewError as exc:
            return exc.as_result()
        ref_key = "console_artifact_id" if field_name == "runtime" else "artifact_id"
        frontend_bundle[field_name] = {ref_key: artifact_id, **context_value}
    if network_artifact_id:
        content, error = resolve_artifact(network_artifact_id, VISION_MAX_BUNDLE_CHARS)
        if error:
            return error
        runtime_value = frontend_bundle.get("runtime")
        runtime_value = dict(runtime_value) if isinstance(runtime_value, dict) else {}
        runtime_value.update(
            {"network_artifact_id": network_artifact_id, "network_content": content}
        )
        frontend_bundle["runtime"] = runtime_value

    inline_aliases = {
        "dom": ("dom", "html"),
        "accessibility": ("accessibility", "accessibility_snapshot"),
        "computed_styles": ("computed_styles", "computed_style_data"),
        "runtime": ("runtime", "runtime_context"),
    }
    for field_name, aliases in inline_aliases.items():
        supplied = next((args[name] for name in aliases if name in args and args[name] is not None), None)
        if supplied is not None:
            try:
                frontend_bundle[field_name] = parse_context_value(field_name, supplied)
            except FrontendReviewError as exc:
                return exc.as_result()
    for field_name in ("viewport", "page", "source"):
        if field_name in args and args.get(field_name) is not None:
            frontend_bundle[field_name] = args[field_name]
    if image_artifact_id:
        frontend_bundle.setdefault("screenshot", {"artifact_id": image_artifact_id})

    for field_name in ("dom", "accessibility", "computed_styles", "runtime"):
        value = frontend_bundle.get(field_name)
        if isinstance(value, dict) and isinstance(value.get("content"), str):
            try:
                decoded_value = parse_context_value(field_name, value["content"])
            except FrontendReviewError as exc:
                return exc.as_result()
            ref = str(value.get("artifact_id", ""))
            frontend_bundle[field_name] = {"artifact_id": ref, **decoded_value} if ref else decoded_value

    model_context = None
    if any(key in frontend_bundle for key in ("dom", "accessibility", "computed_styles", "runtime")):
        try:
            dom_value = frontend_bundle.get("dom") or {}
            accessibility_value = frontend_bundle.get("accessibility") or {}
            styles_value = frontend_bundle.get("computed_styles") or {}
            runtime_value = frontend_bundle.get("runtime") or {}
            model_context = build_model_context(
                prompt=prompt,
                screenshot_data_url=images[0] if images else "",
                dom=dom_value if isinstance(dom_value, dict) else parse_context_value("dom", dom_value),
                accessibility=accessibility_value if isinstance(accessibility_value, dict) else parse_context_value("accessibility", accessibility_value),
                computed_styles=styles_value if isinstance(styles_value, dict) else parse_context_value("computed_styles", styles_value),
                viewport=frontend_bundle.get("viewport") or {},
                runtime=runtime_value if isinstance(runtime_value, dict) else parse_context_value("runtime", runtime_value),
            )
            if model_context.dom.get("truncated"):
                return FrontendReviewError(
                    "frontend_dom_context_truncated",
                    "vision review requires complete live DOM within the configured bound",
                    original_chars=model_context.dom.get("original_chars"),
                    limit_chars=model_context.dom.get("limit_chars"),
                ).as_result()
            for field_name, value in (
                ("dom", model_context.dom),
                ("accessibility", model_context.accessibility),
                ("computed_styles", model_context.computed_styles),
                ("runtime", model_context.runtime),
            ):
                original = frontend_bundle.get(field_name)
                ref = original.get("artifact_id", "") if isinstance(original, dict) else ""
                frontend_bundle[field_name] = {"artifact_id": ref, **value} if ref else value
        except FrontendReviewError as exc:
            return exc.as_result()

    if not images:
        return input_error("Vision image path, base64 data, or image artifact is required.")

    image_size = image_dimensions(base64.b64decode(images[0], validate=True))

    return VisionInputs(
        images=images,
        image_artifact_id=image_artifact_id,
        bundle_artifact_id=bundle_artifact_id,
        bundle_context=bundle_context,
        frontend_bundle=frontend_bundle,
        model_context=model_context,
        image_size=image_size,
    )
