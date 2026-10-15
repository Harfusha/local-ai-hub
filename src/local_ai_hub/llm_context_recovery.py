"""Provider-independent context recovery without dropping caller input."""
from __future__ import annotations

import hashlib
from typing import Any

from .json_utils import dumps as json_dumps


def recovery_route(model: str, entry: dict[str, Any]) -> dict[str, Any] | None:
    try:
        context = int(entry.get("context_length", 0) or 0)
    except (ValueError, TypeError, OverflowError):
        return None
    reduced = context // 2
    if reduced < 1024:
        return None
    original_alias = str(entry.get("served_model") or model)
    identity = json_dumps([original_alias, context])
    alias = "lah-oom-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return {**entry, "served_model": alias, "context_length": reduced,
            "recovery_original_context": context, "recovery_original_alias": original_alias}


def memory_allocation_error(error: Any) -> bool:
    text = str(error).lower()
    return any(marker in text for marker in (
        "out of memory", "not enough memory", "failed to allocate", "cannot allocate memory",
        "std::bad_alloc", "cl_mem_object_allocation_failure", "sycl memory allocation",
    ))


def fit_recovered_context(payload: dict[str, Any], original_context: int,
                          effective_context: int) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    options = payload.get("options")
    if options is not None and not isinstance(options, dict):
        return None, {"reason": "invalid_context_options"}
    options = dict(options or {})
    try:
        requested = int(options.get("num_ctx", original_context) or original_context)
        predicted = int(options.get("num_predict", 256))
    except (TypeError, ValueError, OverflowError):
        return None, {"reason": "invalid_context_options"}
    effective = min(requested, effective_context)
    metadata = {"original_num_ctx": requested, "effective_num_ctx": effective,
                "original_server_num_ctx": original_context, "effective_server_num_ctx": effective_context,
                "input_truncated": False, "device_changed": False}
    if effective < 1024:
        return None, {**metadata, "reason": "context_floor"}
    messages = payload.get("messages")
    if payload.get("images") or (isinstance(messages, list) and any(
        isinstance(message, dict) and (message.get("images") or isinstance(message.get("content"), list))
        for message in messages
    )):
        return None, {**metadata, "reason": "multimodal_input_budget_unknown"}
    retained = {key: payload[key] for key in (
        "prompt", "system", "messages", "suffix", "tools", "functions", "format", "template",
    ) if key in payload}
    try:
        input_bytes = len(json_dumps(retained, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError, UnicodeError, OverflowError):
        return None, {**metadata, "reason": "invalid_input_budget"}
    reserve = max(256, predicted if predicted > 0 else 1024) + 256
    if input_bytes + reserve > effective:
        return None, {**metadata, "reason": "retained_input_exceeds_reduced_budget",
                      "input_budget_basis": "serialized_utf8_bytes_plus_generation_reserve"}
    options["num_ctx"] = effective
    return {**payload, "options": options}, {**metadata, "reason": "native_preset_context_halved"}
