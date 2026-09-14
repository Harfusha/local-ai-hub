from __future__ import annotations

import copy
import json
from typing import Any, Iterable


_PROFILE_FIELDS: dict[str, tuple[str, ...] | None] = {
    "minimal": ("success", "status", "work_id", "task_id", "handoff_id", "artifact_id", "error", "needs_agent"),
    "compact": (
        "success", "status", "work_id", "task_id", "summary", "progress", "changed_files",
        "validation", "risks", "needs_agent", "question", "handoff_id", "artifact_id", "available_details", "error",
    ),
    "standard": (
        "success", "status", "work_id", "task_id", "summary", "progress", "plan", "steps", "changed_files",
        "validation", "verification", "risks", "decisions", "needs_agent", "question", "handoff_id", "artifact_id",
        "available_details", "error",
    ),
    "debug": None,
}


def _dense(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: max(1, limit - 16)].rstrip() + " […truncated…]"


def _bound(value: Any, chars: int, depth: int = 0) -> Any:
    if depth > 8:
        return "[…depth…]"
    if isinstance(value, str):
        return _dense(value, chars)
    if isinstance(value, list):
        return [_bound(v, chars, depth + 1) for v in value[:32]]
    if isinstance(value, dict):
        return {str(k): _bound(v, chars, depth + 1) for k, v in list(value.items())[:64]}
    return value


def project_response(
    value: Any,
    *,
    profile: str = "compact",
    return_fields: Iterable[str] | None = None,
    max_output_tokens: int = 0,
) -> Any:
    """Project a canonical result into a compact agent-to-agent payload.

    Projection is intentionally last-mile only: canonical work, artifacts and caches
    keep their full data. ``return_fields`` is an allow-list and never causes new
    information to be generated. ``max_output_tokens`` is a conservative JSON-size
    budget (roughly four UTF-8 characters/token) with a hard lower bound for IDs/errors.
    """
    if not isinstance(value, dict):
        return value
    canonical = copy.deepcopy(value)
    profile = str(profile or "compact").strip().lower()
    if profile not in _PROFILE_FIELDS:
        profile = "compact"
    fields = [str(x).strip() for x in (return_fields or ()) if str(x).strip()]
    if fields:
        # Explicit projection is authoritative and may request fields outside the
        # profile's default surface. Profiles are defaults, not a second hidden deny-list.
        always = {k for k in ("success", "status", "work_id", "task_id", "error", "needs_agent") if k in canonical}
        selected = {k: canonical[k] for k in canonical if k in set(fields) | always}
    else:
        allowed = _PROFILE_FIELDS[profile]
        selected = canonical if allowed is None else {k: canonical[k] for k in allowed if k in canonical}

    token_budget = int(max_output_tokens or 0)
    if token_budget <= 0:
        token_budget = {"minimal": 120, "compact": 350, "standard": 900, "debug": 2400}[profile]
    token_budget = max(64, min(token_budget, 4096))
    char_budget = token_budget * 4
    per_string = max(160, min(5000, char_budget // 2))
    bounded = _bound(selected, per_string)
    try:
        raw = json.dumps(bounded, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return bounded
    if len(raw) <= char_budget:
        return bounded

    # Preserve decision-grade fields and progressively trim verbose collections.
    out = dict(bounded)
    for key in ("steps", "plan", "verification", "decisions", "risks", "changed_files"):
        if isinstance(out.get(key), list) and len(out[key]) > 4:
            out[key] = out[key][:4]
            out[f"{key}_omitted"] = True
        elif isinstance(out.get(key), dict) and key in {"plan", "verification"}:
            out[key] = {k: v for k, v in list(out[key].items())[:6]}
        try:
            if len(json.dumps(out, ensure_ascii=False, separators=(",", ":"))) <= char_budget:
                return out
        except Exception:
            pass
    if isinstance(out.get("summary"), str):
        out["summary"] = _dense(out["summary"], max(120, char_budget // 3))
    out["truncated"] = True
    try:
        if len(json.dumps(out, ensure_ascii=False, separators=(",", ":"))) <= char_budget:
            return out
    except Exception:
        return out

    # Last-resort envelope: drop the least decision-critical fields until the
    # requested wire budget is met. Full data remains in the canonical result or
    # artifact, so this never destroys stored evidence.
    protected = {"success", "status", "work_id", "task_id", "error", "needs_agent", "handoff_id", "artifact_id"}
    drop_order = [
        "steps", "plan", "verification", "decisions", "available_details", "changed_files",
        "validation", "risks", "progress", "question", "summary",
    ]
    for key in drop_order:
        if key in out and key not in protected:
            out.pop(key, None)
            try:
                if len(json.dumps(out, ensure_ascii=False, separators=(",", ":"))) <= char_budget:
                    return out
            except Exception:
                return out
    # IDs and errors are bounded too, but are retained rather than silently removed.
    for key in tuple(protected):
        if isinstance(out.get(key), str):
            out[key] = _dense(out[key], max(32, char_budget // 4))
    return out
