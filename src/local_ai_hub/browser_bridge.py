"""Explicit, one-shot current-tab capture protocol.

The browser extension is deliberately a dumb transport.  This module owns the
capability, tenant, size, and credential-bearing payload checks before anything
is written to the artifact store.
"""

from __future__ import annotations

import base64
import binascii
import json
import secrets
import threading
import time
from datetime import datetime, timezone
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit


CAPTURE_ERROR_STATUSES = {
    "unsupported": 501,
    "permission_denied": 403,
    "closed_tab": 410,
    "tab_mismatch": 409,
    "window_mismatch": 409,
    "target_changed": 409,
    "timeout": 408,
}
_SENSITIVE_KEYS = {
    "authorization",
    "auth_headers",
    "cookie",
    "cookies",
    "credentials",
    "form_values",
    "network_bodies",
    "password_values",
    "request_bodies",
    "response_bodies",
}
_NETWORK_BODY_KEYS = {"body", "headers", "request_body", "response_body"}
_DEFAULTS = {
    "capability_ttl_seconds": 60,
    "max_payload_bytes": 12 * 1024 * 1024,
    "max_screenshot_bytes": 8 * 1024 * 1024,
    "max_dom_chars": 2_000_000,
    "max_context_chars": 1_000_000,
    "max_elements": 256,
}


class CaptureProtocolError(ValueError):
    """A safe, stable protocol failure for HTTP and test callers."""

    def __init__(self, error_code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.status = status


_capabilities: dict[str, dict[str, Any]] = {}
_capability_lock = threading.Lock()


def _bridge_config(config: Any) -> Mapping[str, Any]:
    if isinstance(config, Mapping):
        value = config.get("browser_bridge", config)
    else:
        value = getattr(config, "browser_bridge", config)
    return value if isinstance(value, Mapping) else vars(value) if hasattr(value, "__dict__") else {}


def _setting(config: Any, key: str) -> Any:
    section = _bridge_config(config)
    value = section.get(key, _DEFAULTS.get(key))
    return value


def _allowed_origins(config: Any) -> list[str]:
    section = _bridge_config(config)
    value = section.get("allowed_origins", getattr(config, "allowed_origins", []))
    if isinstance(value, str):
        value = [value]
    return [str(item).strip() for item in value or [] if str(item).strip()]


def _enabled(config: Any) -> bool:
    return bool(_setting(config, "enabled") if "enabled" in _bridge_config(config) else True)


def _origin_allowed(origin: str, config: Any) -> bool:
    allowed = _allowed_origins(config)
    if not allowed:
        return False
    return any(origin == item or (item.endswith("*") and origin.startswith(item[:-1])) for item in allowed)


def origin_allowed(config: Any, origin: str) -> bool:
    """Public origin check shared by the HTTP CORS guard and capability route."""
    return _origin_allowed(str(origin or "").strip(), config)


def _result_error(error_code: str, message: str, *, status: int = 400, **details: Any) -> dict[str, Any]:
    return {
        "success": False,
        "terminal": True,
        "retryable": False,
        "error": message,
        "error_code": error_code,
        "status": status,
        **details,
    }


def issue_capture_capability(
    config: Any,
    *,
    origin: str,
    tenant: str = "generic",
    tab_id: int | str | None = None,
    window_id: int | str | None = None,
    api_token_authorized: bool = False,
) -> str:
    """Issue a short-lived capability bound to one extension origin and tab."""
    if not _enabled(config):
        raise CaptureProtocolError("unsupported", "current-tab browser bridge is disabled", status=501)
    normalized_origin = str(origin or "").strip()
    if not normalized_origin or (not _origin_allowed(normalized_origin, config) and not api_token_authorized):
        raise CaptureProtocolError("permission_denied", "browser bridge origin is not permitted", status=403)
    if tab_id is None or str(tab_id).strip() == "":
        raise CaptureProtocolError("missing_tab_id", "current-tab capability requires an explicit tab_id", status=400)
    if window_id is None or str(window_id).strip() == "":
        raise CaptureProtocolError("missing_window_id", "current-tab capability requires an explicit window_id", status=400)
    token = secrets.token_urlsafe(32)
    now = time.monotonic()
    record = {
        "tenant": str(tenant or "generic"),
        "origin": normalized_origin,
        "tab_id": str(tab_id),
        "window_id": str(window_id),
        "expires_at": now + max(1.0, float(_setting(config, "capability_ttl_seconds"))),
        "created_at": now,
        "used": False,
    }
    with _capability_lock:
        for stale_token, stale in list(_capabilities.items()):
            if stale.get("used") or float(stale.get("expires_at", 0)) <= now:
                _capabilities.pop(stale_token, None)
        if len(_capabilities) >= 1024:
            oldest = min(_capabilities, key=lambda item: float(_capabilities[item].get("created_at", 0)))
            _capabilities.pop(oldest, None)
        _capabilities[token] = record
    return token


def validate_capture_request(
    capability: str,
    request: Mapping[str, Any],
    *,
    tenant: str | None = None,
) -> dict[str, Any]:
    """Consume a capability only after origin, tenant, and tab all match."""
    token = str(capability or "").strip()
    with _capability_lock:
        record = _capabilities.get(token)
        if not record:
            return _result_error("invalid_capability", "capture capability is invalid or expired", status=403)
        if record["used"]:
            return _result_error("capability_replayed", "capture capability has already been consumed", status=403)
        if time.monotonic() >= float(record["expires_at"]):
            record["used"] = True
            return _result_error("capability_expired", "capture capability has expired", status=403)
        if str(request.get("origin", "")) != record["origin"]:
            return _result_error("origin_mismatch", "capture origin does not match capability", status=403)
        requested_tenant = str(tenant if tenant is not None else request.get("tenant", "generic"))
        if requested_tenant != record["tenant"]:
            return _result_error("capability_tenant_mismatch", "capture tenant does not match capability", status=403)
        requested_tab = request.get("tab_id")
        if requested_tab is None or str(requested_tab).strip() == "":
            return _result_error("missing_tab_id", "capture requires the explicitly requested tab_id")
        if str(requested_tab) != record["tab_id"]:
            return _result_error("tab_mismatch", "capture tab does not match the explicitly requested tab", status=409)
        if record.get("window_id") is not None and str(request.get("window_id", "")).strip() == "":
            return _result_error("missing_window_id", "capture requires the explicitly requested window_id")
        if record.get("window_id") is not None and str(request.get("window_id")) != record["window_id"]:
            return _result_error("window_mismatch", "capture window does not match the explicitly requested window", status=409)
        record["used"] = True
    return {"success": True, "tenant": record["tenant"], "tab_id": record["tab_id"], "window_id": record.get("window_id")}


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _contains_forbidden_keys(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).strip().lower()
            if normalized in _SENSITIVE_KEYS:
                return True
            if _contains_forbidden_keys(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_keys(item) for item in value)
    return False


def _validate_network_refs(runtime: Mapping[str, Any]) -> None:
    for field in ("network_refs", "network", "requests", "responses"):
        refs = runtime.get(field, [])
        if not isinstance(refs, list) or len(refs) > 128:
            raise CaptureProtocolError("invalid_runtime_refs", f"{field} must be a bounded list")
        for ref in refs:
            if not isinstance(ref, Mapping) or any(str(key).lower() in _NETWORK_BODY_KEYS for key in ref):
                raise CaptureProtocolError("credential_bearing_capture_fields", "credential-bearing capture fields are not allowed")


def _screenshot_bytes(value: Any, *, max_bytes: int) -> tuple[bytes, str]:
    if isinstance(value, Mapping):
        mime = str(value.get("mime_type", ""))
        encoded = str(value.get("data", ""))
    else:
        encoded = str(value or "")
        mime = ""
    if encoded.startswith("data:"):
        header, separator, encoded = encoded.partition(",")
        mime = header[5:].split(";", 1)[0].lower()
        if not separator:
            raise CaptureProtocolError("invalid_screenshot", "screenshot data URL is invalid")
    mime = mime or "image/png"
    if mime not in {"image/png", "image/jpeg", "image/webp"}:
        raise CaptureProtocolError("invalid_screenshot", "screenshot MIME type is unsupported")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError, binascii.Error) as exc:
        raise CaptureProtocolError("invalid_screenshot", "screenshot is not valid base64") from exc
    if not decoded or len(decoded) > max_bytes:
        raise CaptureProtocolError("screenshot_too_large", "screenshot exceeds the bounded byte limit")
    return decoded, mime


def validate_capture_payload(payload: Mapping[str, Any], *, config: Any | None = None) -> dict[str, Any]:
    """Validate an extension payload without redacting DOM semantics."""
    if not isinstance(payload, Mapping):
        return _result_error("invalid_capture_payload", "capture payload must be an object")
    if "capture_error" in payload:
        return capture_failure(str(payload.get("capture_error", "unsupported")))
    try:
        if _json_size(payload) > int(_setting(config or {}, "max_payload_bytes")):
            return _result_error("payload_too_large", "capture payload exceeds the bounded byte limit", status=413)
    except (TypeError, ValueError, OverflowError):
        return _result_error("invalid_capture_payload", "capture payload is not serializable")
    if _contains_forbidden_keys(payload):
        return _result_error("credential_bearing_capture_fields", "credential-bearing capture fields are not allowed")
    if "tab_id" not in payload:
        return _result_error("missing_tab_id", "current-tab capture requires the explicitly selected tab_id")
    if payload.get("tab_id") is None or str(payload.get("tab_id")).strip() == "":
        return _result_error("missing_tab_id", "current-tab capture requires the explicitly selected tab_id")
    if "captured_at" in payload and not _safe_capture_timestamp(payload.get("captured_at")):
        return _result_error("invalid_capture_timestamp", "capture timestamp is invalid or unbounded")
    try:
        _screenshot_bytes(payload.get("screenshot"), max_bytes=int(_setting(config or {}, "max_screenshot_bytes")))
    except CaptureProtocolError as exc:
        return _result_error(exc.error_code, str(exc), status=exc.status)
    dom = payload.get("dom")
    if not isinstance(dom, Mapping):
        return _result_error("invalid_dom", "current-tab capture requires a DOM object")
    if dom.get("redaction") != "none":
        return _result_error("missing_dom_redaction" if "redaction" not in dom else "semantic_dom_redaction_not_allowed", "live DOM must include explicit redaction=none")
    html = dom.get("html")
    if not isinstance(html, str):
        return _result_error("invalid_dom", "live DOM html must be a string")
    if len(html) > int(_setting(config or {}, "max_dom_chars")):
        return _result_error("dom_too_large", "live DOM exceeds the bounded character limit", status=413)
    derived_origin = _safe_origin(payload.get("url"))
    if not derived_origin:
        return _result_error("invalid_target_origin", "current-tab capture requires a valid target origin")
    if "target_origin" in payload and _safe_origin(payload.get("target_origin")) != derived_origin:
        return _result_error("target_origin_mismatch", "target-origin provenance does not match the captured page", status=409)
    identity = payload.get("capture_identity")
    if not isinstance(identity, Mapping):
        return _result_error("invalid_capture_identity", "capture requires bounded initial and final document identity")
    initial_identity = _capture_identity(identity.get("initial"))
    final_identity = _capture_identity(identity.get("final"))
    if initial_identity is None or final_identity is None:
        return _result_error("invalid_capture_identity", "capture document identity is invalid or unbounded")
    if initial_identity != final_identity:
        return _result_error("target_changed", "the explicitly requested tab navigated during capture", status=409, fallback=False)
    if initial_identity["url"] != str(payload.get("url", "")) or initial_identity["target_origin"] != derived_origin:
        return _result_error("target_changed", "capture identity does not match the captured page", status=409, fallback=False)
    elements = dom.get("elements")
    if not isinstance(elements, list):
        return _result_error("missing_dom_elements", "live DOM requires a stable elements list")
    if len(elements) > int(_setting(config or {}, "max_elements")):
        return _result_error("too_many_elements", "live DOM contains too many stable elements", status=413)
    element_ids: set[str] = set()
    for element in elements:
        if not isinstance(element, Mapping) or not str(element.get("element_id", "")).strip():
            return _result_error("missing_dom_element_id", "every live DOM element requires a stable element_id")
        element_id = str(element["element_id"])
        if element_id in element_ids:
            return _result_error("duplicate_dom_element_id", "stable DOM element_id values must be unique")
        element_ids.add(element_id)
    for field in ("accessibility", "computed_styles", "runtime"):
        if field in payload and not isinstance(payload[field], Mapping):
            return _result_error("invalid_capture_payload", f"{field} must be an object")
    runtime = payload.get("runtime", {})
    if isinstance(runtime, Mapping):
        try:
            _validate_network_refs(runtime)
            if _json_size(runtime) > int(_setting(config or {}, "max_context_chars")):
                return _result_error("runtime_too_large", "runtime refs exceed the bounded character limit", status=413)
        except CaptureProtocolError as exc:
            return _result_error(exc.error_code, str(exc), status=exc.status)
    return {"success": True, "payload": dict(payload)}


def capture_failure(error_code: str) -> dict[str, Any]:
    code = str(error_code or "unsupported").strip().lower()
    status = CAPTURE_ERROR_STATUSES.get(code, 400)
    messages = {
        "unsupported": "current-tab browser capture is unsupported",
        "permission_denied": "browser denied capture permission",
        "closed_tab": "the explicitly requested tab is closed or unavailable",
        "tab_mismatch": "the active tab changed during capture; no fallback tab was captured",
        "window_mismatch": "the active browser window changed during capture",
        "target_changed": "the explicitly requested tab navigated during capture; no artifact was committed",
        "timeout": "current-tab capture timed out",
    }
    return _result_error(code, messages.get(code, "current-tab capture failed"), status=status, fallback=False)


def _safe_url(value: Any) -> str:
    parsed = urlsplit(str(value or ""))
    origin = _safe_origin(value)
    if not origin:
        return ""
    return f"{origin}{parsed.path}"[:4096]


def _safe_origin(value: Any) -> str:
    parsed = urlsplit(str(value or ""))
    if parsed.username or parsed.password or not parsed.scheme or not parsed.netloc:
        return ""
    try:
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return ""
    if not host:
        return ""
    host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    origin = f"{parsed.scheme.lower()}://{host.lower()}" + (f":{port}" if port is not None else "")
    return origin if len(origin) <= 256 else ""


def _safe_capture_timestamp(value: Any) -> str:
    raw = str(value or "")
    if not raw or len(raw) > 64:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        return ""
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _capture_identity(value: Any) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    url = str(value.get("url", ""))
    origin = _safe_origin(value.get("target_origin"))
    token = str(value.get("document_token", ""))
    if not url or len(url) > 4096 or not origin or not token or len(token) > 256:
        return None
    return {"url": url, "target_origin": origin, "document_token": token}


def _safe_runtime(runtime: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(runtime.get("console_refs"), list):
        result["console_refs"] = [str(item)[:160] for item in runtime["console_refs"][:128]]
    if isinstance(runtime.get("network_refs"), list):
        refs: list[dict[str, Any]] = []
        for raw in runtime["network_refs"][:128]:
            if not isinstance(raw, Mapping):
                continue
            ref = {key: raw[key] for key in ("request_id", "method", "status", "type", "initiator", "resource_type") if key in raw}
            if "url" in raw:
                ref["url"] = _safe_url(raw["url"])
            refs.append(ref)
        result["network_refs"] = refs
    for key in ("console_artifact_id", "network_artifact_id"):
        if runtime.get(key):
            result[key] = str(runtime[key])[:160]
    return result


def capture_to_artifacts(payload: Mapping[str, Any], *, artifacts: Any, tenant: str, config: Any) -> dict[str, Any]:
    checked = validate_capture_payload(payload, config=config)
    if not checked.get("success"):
        return checked
    value = checked["payload"]
    try:
        screenshot, mime = _screenshot_bytes(value["screenshot"], max_bytes=int(_setting(config, "max_screenshot_bytes")))
        dom_id = artifacts.put_json(dict(value["dom"]), tenant, "browser-dom")
        accessibility_id = artifacts.put_json(dict(value.get("accessibility", {})), tenant, "browser-accessibility")
        styles_id = artifacts.put_json(dict(value.get("computed_styles", {})), tenant, "browser-computed-styles")
        runtime_id = artifacts.put_json(_safe_runtime(value.get("runtime", {})), tenant, "browser-runtime")
        screenshot_id = artifacts.put_bytes(screenshot, tenant, "browser-screenshot", mime)
        bundle = {
            "version": 1,
            "source": "current-tab",
            "tab_id": str(value["tab_id"]),
            "page": {"url": _safe_url(value.get("url")), "title": str(value.get("title", ""))[:512]},
            "provenance": {
                "captured_at": _safe_capture_timestamp(value.get("captured_at"))
                or datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "target_origin": _capture_identity(value["capture_identity"]["initial"])["target_origin"],
                "document_token": _capture_identity(value["capture_identity"]["initial"])["document_token"],
            },
            "screenshot": {"artifact_id": screenshot_id, "mime_type": mime},
            "dom": {"artifact_id": dom_id, "format": "live-dom", "redaction": "none"},
            "accessibility": {"artifact_id": accessibility_id, "format": "accessibility-snapshot"},
            "computed_styles": {"artifact_id": styles_id, "format": "computed-styles"},
            "runtime": {"artifact_id": runtime_id, "format": "runtime-refs"},
            "viewport": dict(value.get("viewport", {})) if isinstance(value.get("viewport"), Mapping) else {},
        }
        bundle_id = artifacts.put_json(bundle, tenant, "frontend-review-bundle")
    except Exception as exc:
        return _result_error("artifact_store_error", "browser capture artifact storage failed; retry the request", status=503)
    return {
        "success": True,
        "bundle_artifact_id": bundle_id,
        "screenshot_artifact_id": screenshot_id,
        "dom_artifact_id": dom_id,
        "accessibility_artifact_id": accessibility_id,
        "computed_styles_artifact_id": styles_id,
        "runtime_artifact_id": runtime_id,
        "tenant": str(tenant),
        "page": bundle["page"],
        "tab_id": bundle["tab_id"],
    }
