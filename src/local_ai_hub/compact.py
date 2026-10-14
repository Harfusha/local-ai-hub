from __future__ import annotations

import math
from typing import Any, Iterable


def syntax_aware_truncate(text: str, max_chars: int, marker: str = "\n[... compact MCP projection ...]") -> str:
    """Truncate text/code cleanly on line boundaries and avoid breaking JSON or code syntax."""
    if not isinstance(text, str):
        return text
    text = text.replace("\x00", "")
    if not isinstance(max_chars, int) or isinstance(max_chars, bool):
        try:
            if isinstance(max_chars, float) and (math.isnan(max_chars) or math.isinf(max_chars)):
                max_chars = 0
            else:
                max_chars = int(max_chars)
        except (ValueError, TypeError):
            max_chars = 0
    if max_chars <= 0:
        return ""
    marker_str = str(marker).replace("\x00", "") if marker is not None else ""
    if len(text) <= max_chars:
        return text
    if max_chars < len(marker_str):
        return text[:max_chars]
    budget = max(64, max_chars - len(marker_str))
    prefix = text[:budget]
    last_nl = prefix.rfind("\n")
    if last_nl > int(budget * 0.7):
        prefix = prefix[:last_nl]
    trimmed = prefix.strip()
    if trimmed.startswith("{") and not trimmed.endswith("}"):
        return prefix + "\n  // ... remaining structure omitted ...\n}"
    if trimmed.startswith("[") and not trimmed.endswith("]"):
        return prefix + "\n  // ... remaining items omitted ...\n]"
    return prefix + marker_str


def compact_result(
    value: Any,
    *,
    max_text_chars: int = 1800,
    max_evidence: int = 10,
    max_items: int = 50,
    extra_fields: Iterable[str] | str | None = None,
    _depth: int = 0,
    _seen: set[int] | None = None,
) -> Any:
    """Remove low-value runtime detail before an MCP result enters cloud context.

    The full hub HTTP API remains unchanged. This is an agent-facing projection only.
    """
    try:
        max_text_chars = max(64, int(max_text_chars))
    except (ValueError, TypeError):
        max_text_chars = 1800
    try:
        max_evidence = max(0, int(max_evidence))
    except (ValueError, TypeError):
        max_evidence = 10
    try:
        max_items = max(0, int(max_items))
    except (ValueError, TypeError):
        max_items = 50

    if _seen is None:
        _seen = set()
    if _depth > 10:
        return value

    if isinstance(value, (dict, list)):
        val_id = id(value)
        if val_id in _seen:
            return value
        _seen = set(_seen)
        _seen.add(val_id)

    if isinstance(extra_fields, str):
        extra_fields = [extra_fields]
    extra = {str(x).strip().replace("\x00", "") for x in (extra_fields or ())} if extra_fields else set()
    extra.discard("")

    if isinstance(value, list):
        return [
            compact_result(
                v,
                max_text_chars=max_text_chars,
                max_evidence=max_evidence,
                max_items=max_items,
                extra_fields=extra,
                _depth=_depth + 1,
                _seen=_seen,
            )
            for v in value[:max_items]
        ]
    if not isinstance(value, dict):
        return value

    # Copy only containers we actually mutate. A full deepcopy of large repository
    # evidence/diff/artifact payloads was a measurable foreground hot-path cost even
    # though most nested values are only read or replaced below.
    data = dict(value)
    # Low-level Ollama timing/counter fields belong in telemetry, not every tool result.
    for key in (
        "load_duration_ns", "eval_count", "prompt_eval_count", "total_duration_ns",
        "job_id", "prompt_budget",
    ):
        if key not in extra:
            data.pop(key, None)

    if isinstance(data.get("text"), str) and len(data["text"]) > max_text_chars:
        data["text"] = syntax_aware_truncate(data["text"], max_text_chars)

    # Command output is aggressively bounded; a full-log artifact is optional.
    output_artifact_available = bool(data.get("output_artifact_id"))
    if isinstance(data.get("summary"), str) and len(data["summary"]) > max_text_chars:
        data["summary"] = syntax_aware_truncate(data["summary"], max_text_chars, marker="\n[... summary truncated ...]")
    stream_budget = max(256, max_text_chars // 3)
    if isinstance(data.get("stdout"), str) and len(data["stdout"]) > stream_budget:
        marker = "\n[... stdout truncated; use artifact ...]" if output_artifact_available else "\n[... stdout truncated ...]"
        data["stdout"] = data["stdout"][:stream_budget] + marker
        data["output_truncated"] = True
    if isinstance(data.get("stderr"), str) and len(data["stderr"]) > stream_budget:
        data["stderr"] = data["stderr"][-stream_budget:]
        marker = "[... stderr head omitted; use artifact ...]" if output_artifact_available else "[... stderr head omitted ...]"
        data["stderr"] = marker + "\n" + data["stderr"]
        data["output_truncated"] = True

    repo_context = data.get("repo_context")
    if isinstance(repo_context, dict) and isinstance(repo_context.get("evidence"), list):
        repo_context = dict(repo_context)
        data["repo_context"] = repo_context
        total = len(repo_context["evidence"])
        repo_context["evidence"] = repo_context["evidence"][:max_evidence]
        if total > max_evidence:
            repo_context["evidence_omitted"] = total - max_evidence

    if isinstance(data.get("evidence"), list):
        total = len(data["evidence"])
        data["evidence"] = data["evidence"][:max_evidence]
        if total > max_evidence:
            data["evidence_omitted"] = total - max_evidence

    if isinstance(data.get("results"), list):
        new_results = []
        total = len(data["results"])
        for item in data["results"][:max_items]:
            if isinstance(item, dict):
                item = compact_result(
                    item,
                    max_text_chars=min(max_text_chars, 1100),
                    max_evidence=max_evidence,
                    max_items=max_items,
                    extra_fields=extra,
                    _depth=_depth + 1,
                    _seen=_seen,
                )
            new_results.append(item)
        data["results"] = new_results
        if total > max_items:
            data["results_omitted"] = total - max_items

    # Tool responses can wrap service payloads under arbitrary keys (for example
    # structured/canonical/content). Compact nested containers too; otherwise a
    # large inner model or command response bypasses the top-level limits.
    for key, item in list(data.items()):
        if key in {"results", "repo_context"}:
            continue
        if isinstance(item, (dict, list)):
            data[key] = compact_result(
                item,
                max_text_chars=max_text_chars,
                max_evidence=max_evidence,
                max_items=max_items,
                extra_fields=extra,
                _depth=_depth + 1,
                _seen=_seen,
            )

    for key in ("output", "content", "raw", "preview"):
        if isinstance(data.get(key), str) and len(data[key]) > max_text_chars:
            data[key] = syntax_aware_truncate(data[key], max_text_chars)

    return data


def is_compacted(data: Any) -> bool:
    """Check if a data structure contains compaction markers or truncation flags."""
    if not isinstance(data, (dict, list)):
        return False
    if isinstance(data, list):
        return any(is_compacted(item) for item in data)
    if data.get("output_truncated") is True:
        return True
    if "evidence_omitted" in data or "results_omitted" in data:
        return True
    repo_context = data.get("repo_context")
    if isinstance(repo_context, dict) and "evidence_omitted" in repo_context:
        return True
    markers = (
        "[... compact MCP projection ...]",
        "[... summary truncated ...]",
        "[... stdout truncated",
        "[... stderr head omitted",
        "// ... remaining structure omitted ...",
        "// ... remaining items omitted ...",
    )
    for key in ("text", "summary", "stdout", "stderr", "output", "content", "raw", "preview"):
        val = data.get(key)
        if isinstance(val, str) and any(m in val for m in markers):
            return True
    return False


def omitted_counts(data: Any) -> dict[str, int]:
    """Extract dictionary of omitted counts (evidence, results, etc.) from data."""
    counts: dict[str, int] = {}
    if not isinstance(data, dict):
        return counts
    if "evidence_omitted" in data and isinstance(data["evidence_omitted"], int):
        counts["evidence"] = data["evidence_omitted"]
    if "results_omitted" in data and isinstance(data["results_omitted"], int):
        counts["results"] = data["results_omitted"]
    repo_context = data.get("repo_context")
    if isinstance(repo_context, dict) and "evidence_omitted" in repo_context and isinstance(repo_context["evidence_omitted"], int):
        counts["repo_evidence"] = repo_context["evidence_omitted"]
    return counts
