"""Contracts for screenshot-based frontend reviews."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field, replace
from typing import Any


SEVERITIES = {"blocker", "high", "medium", "low", "info"}
CATEGORIES = {
    "layout",
    "responsive",
    "accessibility",
    "interaction",
    "visual-regression",
    "runtime",
}

# Transport and contract bounds keep multimodal requests and returned findings
# predictable even when a local model emits pathological content.
VISION_MAX_PROMPT_CHARS = 16_000
VISION_MAX_SCHEMA_CHARS = 8_000
VISION_MAX_IMAGE_CHARS = 4_000_000
VISION_MAX_BUNDLE_CHARS = 12_000
VISION_MAX_RUNTIME_OUTPUT_CHARS = 64_000
VISION_MAX_INLINE_RESPONSE_CHARS = 12_000
VISION_MAX_FIELD_CHARS = 2_000
VISION_MAX_LIST_ITEMS = 32


@dataclass(frozen=True)
class VisionFinding:
    finding_id: str
    severity: str
    category: str
    problem: str
    confidence: float
    element_ids: tuple[str, ...] = ()
    bbox: tuple[float, float, float, float] | None = None
    evidence: tuple[str, ...] = ()
    likely_cause: str = ""
    fix_hint: str = ""
    needs_runtime_check: bool = True


@dataclass(frozen=True)
class VisionParseResult:
    summary: str = ""
    findings: tuple[VisionFinding, ...] = ()
    unknowns: tuple[str, ...] = ()
    recommended_checks: tuple[str, ...] = ()
    terminal: bool = False
    error: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FrontendReviewBundle:
    schema_version: str
    source: str
    prompt: str
    screenshot_artifact_id: str
    screenshot_mime_type: str
    dom_artifact_id: str = ""
    accessibility_artifact_id: str = ""
    computed_styles_artifact_id: str = ""
    runtime_artifact_id: str = ""
    viewport: dict[str, int | float] = field(default_factory=dict)
    page: dict[str, str] = field(default_factory=dict)
    dom_redaction: str = "none"

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "FrontendReviewBundle":
        screenshot = payload.get("screenshot")
        if not isinstance(screenshot, dict) or not screenshot.get("artifact_id"):
            raise ValueError("screenshot artifact_id is required")
        if not screenshot.get("mime_type"):
            raise ValueError("screenshot mime_type is required")

        dom = payload.get("dom") or {}
        accessibility = payload.get("accessibility") or {}
        styles = payload.get("computed_styles") or {}
        runtime = payload.get("runtime") or {}
        return cls(
            schema_version=str(payload.get("schema_version", "1")),
            source=str(payload.get("source", "upload")),
            prompt=str(payload.get("prompt", "")),
            screenshot_artifact_id=str(screenshot["artifact_id"]),
            screenshot_mime_type=str(screenshot["mime_type"]),
            dom_artifact_id=str(dom.get("artifact_id", "")),
            accessibility_artifact_id=str(accessibility.get("artifact_id", "")),
            computed_styles_artifact_id=str(styles.get("artifact_id", "")),
            runtime_artifact_id=str(
                runtime.get("artifact_id", runtime.get("console_artifact_id", ""))
            ),
            viewport=dict(payload.get("viewport") or {}),
            page=dict(payload.get("page") or {}),
            dom_redaction=str(dom.get("redaction", "none")),
        )


def _json_text(raw: str) -> str:
    text = raw.strip()
    match = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    return match.group(1).strip() if match else text


def _terminal_error(message: str) -> VisionParseResult:
    return VisionParseResult(
        terminal=True,
        error={"code": "malformed_vision_output", "message": str(message)[:VISION_MAX_FIELD_CHARS]},
    )


def _coder_error(message: str) -> dict[str, Any]:
    return {
        "terminal": True,
        "error": {"code": "malformed_coder_context", "message": message},
    }


def parse_vision_result(raw: str) -> VisionParseResult:
    try:
        payload = json.loads(_json_text(raw))
        if not isinstance(payload, dict) or not isinstance(payload.get("findings"), list):
            return _terminal_error("findings must be a JSON array")
        findings = []
        for item in payload["findings"]:
            if not isinstance(item, dict):
                return _terminal_error("finding must be an object")
            missing = [
                name
                for name in ("id", "problem", "confidence")
                if name not in item or item[name] in (None, "")
            ]
            if missing:
                return _terminal_error(
                    "finding missing required fields: " + ", ".join(missing)
                )
            severity = item.get("severity")
            category = item.get("category")
            if severity not in SEVERITIES:
                return _terminal_error(f"invalid severity: {severity}")
            if category not in CATEGORIES:
                return _terminal_error(f"invalid category: {category}")
            confidence = float(item.get("confidence", 0.0))
            if not math.isfinite(confidence):
                return _terminal_error("confidence must be finite")
            bbox = item.get("bbox")
            if bbox is not None:
                if not isinstance(bbox, list) or len(bbox) != 4:
                    return _terminal_error("bbox must contain four values")
                bbox = tuple(float(value) for value in bbox)
                if not all(math.isfinite(value) for value in bbox):
                    return _terminal_error("bbox coordinates must be finite")
            for field_name in ("element_ids", "evidence"):
                value = item.get(field_name, [])
                if not isinstance(value, list) or not all(
                    isinstance(entry, str) for entry in value
                ):
                    return _terminal_error(f"{field_name} must be a list of strings")
            findings.append(
                VisionFinding(
                    finding_id=str(item.get("id", "")),
                    severity=severity,
                    category=category,
                    problem=str(item.get("problem", "")),
                    confidence=max(0.0, min(1.0, confidence)),
                    element_ids=tuple(str(value) for value in item.get("element_ids", [])),
                    bbox=bbox,
                    evidence=tuple(str(value) for value in item.get("evidence", [])),
                    likely_cause=str(item.get("likely_cause", "")),
                    fix_hint=str(item.get("fix_hint", "")),
                    needs_runtime_check=bool(item.get("needs_runtime_check", True)),
                )
            )
    except (json.JSONDecodeError, TypeError, ValueError, OverflowError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("invalid "):
            raise
        return _terminal_error(str(exc))

    optional_lists = {}
    for field_name in ("unknowns", "recommended_checks"):
        value = payload.get(field_name, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return _terminal_error(f"{field_name} must be a list of strings")
        optional_lists[field_name] = tuple(value)

    return VisionParseResult(
        summary=str(payload.get("summary", "")),
        findings=tuple(findings),
        unknowns=optional_lists["unknowns"],
        recommended_checks=optional_lists["recommended_checks"],
    )


def bound_vision_result(result: VisionParseResult) -> VisionParseResult:
    """Bound model-controlled strings before exposing a parsed review."""
    bound = lambda value: str(value)[:VISION_MAX_FIELD_CHARS]
    findings = tuple(
        replace(
            finding,
            finding_id=bound(finding.finding_id),
            problem=bound(finding.problem),
            element_ids=tuple(bound(value) for value in finding.element_ids[:VISION_MAX_LIST_ITEMS]),
            evidence=tuple(bound(value) for value in finding.evidence[:VISION_MAX_LIST_ITEMS]),
            likely_cause=bound(finding.likely_cause),
            fix_hint=bound(finding.fix_hint),
        )
        for finding in result.findings[:VISION_MAX_LIST_ITEMS]
    )
    return replace(
        result,
        summary=bound(result.summary),
        findings=findings,
        unknowns=tuple(bound(value) for value in result.unknowns[:VISION_MAX_LIST_ITEMS]),
        recommended_checks=tuple(
            bound(value) for value in result.recommended_checks[:VISION_MAX_LIST_ITEMS]
        ),
    )


def _runtime_projection(value: Any, limit: int) -> Any:
    if isinstance(value, list):
        return value[:limit]
    if isinstance(value, dict):
        return {
            str(key): _runtime_projection(item, limit)
            for key, item in list(value.items())[:limit]
        }
    if isinstance(value, str):
        return value[:2000]
    return value


def build_coder_packet(
    *,
    prompt: str,
    findings: list[dict[str, Any]] | tuple[VisionFinding, ...],
    dom: dict[str, Any] | None = None,
    repo_context: dict[str, Any] | None = None,
    runtime_context: dict[str, Any] | None = None,
    max_runtime_items: int = 20,
) -> dict[str, Any]:
    if not isinstance(findings, (list, tuple)):
        return _coder_error("findings must be a list or tuple")
    if dom is None:
        dom = {}
    if not isinstance(dom, dict):
        return _coder_error("dom must be an object")
    elements = dom.get("elements", [])
    if not isinstance(elements, list):
        return _coder_error("dom.elements must be a list")
    for element in elements:
        if not isinstance(element, dict) or not element.get("element_id"):
            return _coder_error("dom.elements must contain objects with element_id")
        for field_name in ("ancestor_ids", "ancestors"):
            if field_name in element and not isinstance(element[field_name], list):
                return _coder_error(f"dom element {field_name} must be a list")
    by_id = {
        str(element.get("element_id")): element
        for element in elements
        if isinstance(element, dict) and element.get("element_id")
    }
    referenced = set()
    for finding in findings:
        if isinstance(finding, VisionFinding):
            ids = finding.element_ids
        elif isinstance(finding, dict) and isinstance(finding.get("element_ids", []), list):
            ids = finding["element_ids"]
        else:
            return _coder_error("findings must contain valid element_ids lists")
        referenced.update(str(element_id) for element_id in ids)

    kept = set(referenced)
    pending = list(referenced)
    while pending:
        element_id = pending.pop()
        element = by_id.get(element_id, {})
        ancestors = element.get("ancestor_ids", element.get("ancestors", []))
        for ancestor in ancestors if isinstance(ancestors, list) else []:
            ancestor_id = ancestor.get("element_id") if isinstance(ancestor, dict) else ancestor
            if str(ancestor_id) in by_id and str(ancestor_id) not in kept:
                kept.add(str(ancestor_id))
                pending.append(str(ancestor_id))

    packet: dict[str, Any] = {
        "prompt": prompt,
        "findings": findings,
        "dom": {key: value for key, value in dom.items() if key != "elements"},
        "repo": repo_context or {},
    }
    packet["dom"]["elements"] = [element for element in elements if element.get("element_id") in kept]
    if runtime_context is not None:
        if not isinstance(runtime_context, dict):
            return _coder_error("runtime_context must be an object")
        packet["runtime"] = _runtime_projection(
            runtime_context, max(0, max_runtime_items)
        )
    return packet
