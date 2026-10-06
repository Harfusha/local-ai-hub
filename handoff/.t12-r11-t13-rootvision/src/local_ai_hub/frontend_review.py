"""Bounded DOM-aware context helpers for frontend vision reviews."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from .vision_contracts import (
    UNTRUSTED_CONTEXT_INSTRUCTION,
    VISION_MAX_BUNDLE_CHARS,
    VISION_MAX_CONTEXT_DEPTH,
    VisionContextBoundsError,
    build_coder_packet,
    validate_bounded_context,
)


_TRANSPORT_METADATA = {
    "artifact_id",
    "mime_type",
    "encoding",
    "checksum",
    "size_bytes",
    "tenant",
    "tenant_id",
    "path",
    "file_path",
    "absolute_path",
}
_MAX_DOM_ELEMENTS = 256


class FrontendReviewError(ValueError):
    """Terminal input error with stable code for HTTP/MCP callers."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_result(self) -> dict[str, Any]:
        return {
            "success": False,
            "terminal": True,
            "retryable": False,
            "error": {"code": self.code, "message": self.message, **self.details},
            "error_code": self.code,
        }


@dataclass(frozen=True)
class FrontendModelContext:
    prompt: str
    screenshot_data_url: str
    dom: dict[str, Any]
    accessibility: dict[str, Any]
    computed_styles: dict[str, Any]
    viewport: dict[str, Any]
    runtime: dict[str, Any]

    def prompt_payload(self) -> dict[str, Any]:
        """Return model context without duplicating image transport data."""
        return {
            "prompt": self.prompt,
            "context_instructions": UNTRUSTED_CONTEXT_INSTRUCTION,
            "dom": self.dom,
            "accessibility": self.accessibility,
            "computed_styles": self.computed_styles,
            "viewport": self.viewport,
            "runtime": self.runtime,
        }


def _raw_json_depth(value: str) -> int:
    depth = 0
    maximum = 0
    in_string = False
    escaped = False
    for char in value:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            maximum = max(maximum, depth)
        elif char in "]}":
            depth = max(0, depth - 1)
    return maximum


def parse_bounded_context(value: Any, name: str) -> dict[str, Any]:
    """Parse caller-provided context only after cheap raw size/depth checks."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str):
        raise FrontendReviewError("invalid_frontend_context", f"{name} context must be an object")
    if len(value) > VISION_MAX_BUNDLE_CHARS:
        raise FrontendReviewError(
            "frontend_context_too_large",
            f"{name} raw context exceeds the bounded character limit",
        )
    if _raw_json_depth(value) > VISION_MAX_CONTEXT_DEPTH:
        raise FrontendReviewError(
            "frontend_context_too_deep",
            f"{name} raw context exceeds the nesting limit",
        )
    looks_like_json = value.lstrip().startswith(("{", "["))
    try:
        parsed = json.loads(value)
    except RecursionError as exc:
        raise FrontendReviewError(
            "frontend_context_too_deep",
            f"{name} raw context exceeds the nesting limit",
        ) from exc
    except (TypeError, ValueError) as exc:
        if looks_like_json:
            raise FrontendReviewError(
                "invalid_frontend_context",
                f"{name} must contain valid JSON",
            ) from exc
        return {"html": value} if name in {"dom", "html"} else {"text": value}
    if isinstance(parsed, dict):
        return parsed
    raise FrontendReviewError("invalid_frontend_context", f"{name} context must be an object")


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    return parse_bounded_context(value, name)


def _strip_transport_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    # Keep DOM markup and nested element content verbatim. Only remove envelope
    # metadata that should not be duplicated into model context.
    return {key: value for key, value in payload.items() if key not in _TRANSPORT_METADATA}


def project_live_dom(payload: dict[str, Any], *, max_chars: int) -> dict[str, Any]:
    """Project live DOM while preserving semantics and exposing bounds."""
    if not isinstance(payload, dict):
        return FrontendReviewError("invalid_dom_bundle", "live DOM bundle must be an object").as_result()
    if max_chars <= 0:
        return FrontendReviewError("invalid_dom_bound", "DOM character bound must be positive").as_result()

    projected = _strip_transport_metadata(dict(payload))
    has_dom = "html" in projected or "elements" in projected
    if has_dom and "redaction" not in projected:
        return FrontendReviewError(
            "missing_dom_redaction",
            "DOM-aware context requires an explicit redaction=none marker",
        ).as_result()
    if "redaction" in projected and projected.get("redaction") != "none":
        return FrontendReviewError(
            "semantic_dom_redaction_not_allowed",
            "live DOM redaction must be explicitly none; semantic redaction is not allowed",
        ).as_result()
    elements = projected.get("elements")
    if "html" in projected and elements is None:
        return FrontendReviewError(
            "missing_dom_elements",
            "live DOM html requires a stable elements list with element_id values",
        ).as_result()
    if elements is not None:
        if not isinstance(elements, list):
            return FrontendReviewError("invalid_dom_bundle", "dom.elements must be a list").as_result()
        if len(elements) > _MAX_DOM_ELEMENTS:
            return FrontendReviewError(
                "dom_structure_too_large",
                "live DOM contains too many stable elements",
                element_count=len(elements),
                limit_elements=_MAX_DOM_ELEMENTS,
            ).as_result()
        seen: set[str] = set()
        for element in elements:
            if not isinstance(element, dict) or not str(element.get("element_id", "")).strip():
                return FrontendReviewError(
                    "missing_dom_element_id", "every live DOM element requires a stable element_id"
                ).as_result()
            element_id = str(element["element_id"])
            if element_id in seen:
                return FrontendReviewError(
                    "duplicate_dom_element_id", f"duplicate stable DOM element_id: {element_id}"
                ).as_result()
            seen.add(element_id)

    try:
        validate_bounded_context(
            projected,
            name="dom",
            max_chars=max_chars,
            allow_html_paths={"html"},
        )
    except VisionContextBoundsError as exc:
        return FrontendReviewError(exc.code, str(exc)).as_result()
    projected.setdefault("truncated", False)
    return projected


def build_model_context(
    *,
    prompt: str,
    screenshot_data_url: str,
    dom: dict[str, Any],
    accessibility: dict[str, Any],
    computed_styles: dict[str, Any],
    viewport: dict[str, Any],
    runtime: dict[str, Any] | None = None,
) -> FrontendModelContext:
    if not isinstance(screenshot_data_url, str) or not screenshot_data_url:
        raise FrontendReviewError("missing_screenshot", "vision review requires screenshot data")
    if not isinstance(prompt, str):
        raise FrontendReviewError("frontend_context_invalid", "prompt must be a string")
    try:
        validate_bounded_context(prompt, name="prompt")
    except VisionContextBoundsError as exc:
        raise FrontendReviewError(exc.code, str(exc)) from exc
    projected_dom = project_live_dom(dom, max_chars=VISION_MAX_BUNDLE_CHARS)
    if projected_dom.get("terminal"):
        error = projected_dom.get("error", {})
        raise FrontendReviewError(str(error.get("code", "invalid_dom_bundle")), str(error.get("message", "invalid DOM bundle")))
    context = FrontendModelContext(
        prompt=str(prompt),
        screenshot_data_url=screenshot_data_url,
        dom=projected_dom,
        accessibility=_strip_transport_metadata(_mapping(accessibility, "accessibility")),
        computed_styles=_strip_transport_metadata(_mapping(computed_styles, "computed_styles")),
        viewport=_mapping(viewport, "viewport"),
        runtime=_strip_transport_metadata(_mapping(runtime, "runtime")),
    )
    try:
        validate_bounded_context(
            {
                "prompt": context.prompt,
                "dom": context.dom,
                "accessibility": context.accessibility,
                "computed_styles": context.computed_styles,
                "viewport": context.viewport,
                "runtime": context.runtime,
            },
            name="frontend_bundle",
            allow_html_paths={"dom.html"},
        )
    except VisionContextBoundsError as exc:
        raise FrontendReviewError(exc.code, str(exc)) from exc
    return context


def _artifact_id(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("artifact_id", "")).strip()
    return ""


def _runtime_artifact_refs(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    refs = {}
    generic = str(value.get("artifact_id", "")).strip()
    if generic:
        refs["console_artifact_id"] = generic
    for key in ("console_artifact_id", "network_artifact_id"):
        ref = str(value.get(key, "")).strip()
        if ref:
            refs[key] = ref
    return refs


def _context_value(value: Any, name: str) -> dict[str, Any]:
    result = _mapping(value, name)
    content = result.get("content")
    if isinstance(content, str):
        decoded = parse_bounded_context(content, name)
        if set(decoded) in ({"text"}, {"html"}) and next(iter(decoded.values())) == content:
            return result
        if isinstance(decoded, dict):
            result = {**decoded, **{key: value for key, value in result.items() if key != "content"}}
    return result


def _relevant_mapping(value: dict[str, Any], ids: set[str]) -> dict[str, Any]:
    if not value:
        return {}
    if not all(isinstance(key, str) for key in value):
        return value
    if not any(key in ids for key in value):
        return value
    return {key: item for key, item in value.items() if key in ids}


def build_coder_context(
    review: dict[str, Any],
    bundle: dict[str, Any],
    repo_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble actionable, bounded coder context without dropping large DOM silently."""
    if not isinstance(review, dict) or not isinstance(bundle, dict):
        return FrontendReviewError("invalid_coder_context", "review and bundle must be objects").as_result()

    dom = _context_value(bundle.get("dom"), "dom")
    dom_ref = _artifact_id(bundle.get("dom"))
    dom = _strip_transport_metadata(dom)
    if bundle.get("dom_payload") and not dom:
        dom = {"html": str(bundle["dom_payload"])}
    projected_dom = project_live_dom(dom, max_chars=VISION_MAX_BUNDLE_CHARS)
    if projected_dom.get("terminal"):
        return projected_dom
    dom = projected_dom
    if dom.get("truncated"):
        return FrontendReviewError(
            "frontend_dom_context_truncated",
            "coder context requires complete live DOM; provide the full bounded artifact",
            original_chars=dom.get("original_chars"),
            limit_chars=dom.get("limit_chars"),
        ).as_result()

    findings = review.get("findings", [])
    if isinstance(findings, tuple):
        findings = list(findings)
    if not isinstance(findings, list):
        return FrontendReviewError("invalid_coder_context", "review.findings must be a list").as_result()
    findings = [
        {
            **finding,
            "element_ids": list(finding.get("element_ids", [])),
        }
        if isinstance(finding, dict)
        else finding
        for finding in findings
    ]
    dom_elements = dom.get("elements", [])
    element_ids = {
        str(element.get("element_id"))
        for element in dom_elements
        if isinstance(element, dict) and element.get("element_id")
    }
    referenced = {
        str(element_id)
        for finding in findings
        if isinstance(finding, dict)
        for element_id in finding.get("element_ids", [])
        if isinstance(finding.get("element_ids", []), list)
    }
    missing = sorted(referenced - element_ids)
    if missing:
        return FrontendReviewError(
            "unknown_dom_reference",
            "vision finding references DOM elements absent from bundle",
            element_ids=missing,
        ).as_result()

    raw_prompt = bundle.get("prompt", review.get("prompt", ""))
    if not isinstance(raw_prompt, str):
        return FrontendReviewError("frontend_context_invalid", "prompt must be a string").as_result()
    prompt_value = raw_prompt
    accessibility_value = _strip_transport_metadata(
        _context_value(bundle.get("accessibility"), "accessibility")
    )
    styles_value = _strip_transport_metadata(
        _context_value(bundle.get("computed_styles"), "computed_styles")
    )
    runtime_value = _context_value(bundle.get("runtime"), "runtime")
    try:
        validate_bounded_context(
            {
                "prompt": prompt_value,
                "dom": dom,
                "accessibility": accessibility_value,
                "computed_styles": styles_value,
                "runtime": runtime_value,
                "repo": repo_context or {},
            },
            name="coder_context",
            allow_html_paths={"dom.html"},
        )
    except VisionContextBoundsError as exc:
        return FrontendReviewError(exc.code, str(exc)).as_result()

    base = build_coder_packet(
        prompt=prompt_value,
        findings=findings,
        dom=dom,
        repo_context=repo_context,
        runtime_context=runtime_value or None,
    )
    if base.get("terminal"):
        return {"success": False, **base}

    kept_ids = {
        str(element.get("element_id"))
        for element in base.get("dom", {}).get("elements", [])
        if isinstance(element, dict) and element.get("element_id")
    }
    accessibility = _relevant_mapping(
        accessibility_value,
        kept_ids,
    )
    styles = _relevant_mapping(
        styles_value,
        kept_ids,
    )
    refs: dict[str, str] = {}
    for name in ("screenshot", "dom", "accessibility", "computed_styles"):
        ref = _artifact_id(bundle.get(name))
        if ref:
            refs[name] = ref
    runtime_refs = _runtime_artifact_refs(bundle.get("runtime"))
    if runtime_refs:
        refs["runtime"] = runtime_refs
    if dom_ref and "dom" not in refs:
        refs["dom"] = dom_ref

    packet = dict(base)
    packet.update(
        {
            "success": True,
            "review": review,
            "artifact_refs": refs,
            "accessibility": accessibility,
            "computed_styles": styles,
            "viewport": dict(bundle.get("viewport") or {}),
            "page": dict(bundle.get("page") or {}),
        }
    )
    return packet


def run_repair_recheck(
    review: dict[str, Any],
    bundle: dict[str, Any],
    repo_context: dict[str, Any] | None,
    *,
    repair: Callable[[dict[str, Any], int], dict[str, Any]],
    recheck: Callable[[dict[str, Any], int], dict[str, Any]],
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Run an explicit, bounded coder repair followed by browser/test recheck.

    The hub owns orchestration and evidence shape; the caller owns the actual
    edit and browser probe. This keeps screenshot-only review advisory and
    prevents an implicit model response from mutating a repository.
    """
    packet = build_coder_context(review, bundle, repo_context=repo_context)
    if not packet.get("success"):
        return packet
    attempts = max(1, min(int(max_attempts), 5))
    history: list[dict[str, Any]] = []
    current = dict(packet)
    for attempt in range(1, attempts + 1):
        try:
            edit = repair(current, attempt)
        except Exception as exc:
            history.append({"attempt": attempt, "stage": "edit", "error": str(exc)[:300]})
            continue
        if not isinstance(edit, dict) or not edit.get("success", True):
            history.append({"attempt": attempt, "stage": "edit", "result": edit})
            continue
        try:
            checked = recheck(edit, attempt)
        except Exception as exc:
            history.append({"attempt": attempt, "stage": "recheck", "error": str(exc)[:300]})
            continue
        if not isinstance(checked, dict):
            history.append({"attempt": attempt, "stage": "recheck", "error": "recheck must return an object"})
            continue
        remaining = checked.get("findings", [])
        if not isinstance(remaining, list):
            history.append({"attempt": attempt, "stage": "recheck", "error": "recheck.findings must be a list"})
            continue
        active = [
            item for item in remaining
            if isinstance(item, dict) and str(item.get("status", "active")).lower() not in {"cleared", "resolved", "fixed"}
        ]
        history.append({
            "attempt": attempt,
            "stage": "recheck",
            "success": not active,
            "remaining_finding_ids": [str(item.get("finding_id", "")) for item in active],
        })
        if not active:
            return {
                "success": True,
                "repaired": True,
                "attempts": attempt,
                "coder_context": current,
                "recheck": checked,
                "history": history,
            }
        current = {**current, "recheck": checked}
    return {
        "success": False,
        "terminal": True,
        "retryable": False,
        "error_code": "frontend_repair_exhausted",
        "error": {"code": "frontend_repair_exhausted", "message": "frontend repair attempts exhausted"},
        "attempts": attempts,
        "history": history,
        "coder_context": packet,
    }
