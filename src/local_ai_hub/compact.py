from __future__ import annotations

from typing import Any, Iterable


def compact_result(
    value: Any,
    *,
    max_text_chars: int = 1800,
    max_evidence: int = 10,
    extra_fields: Iterable[str] | None = None,
) -> Any:
    """Remove low-value runtime detail before an MCP result enters cloud context.

    The full hub HTTP API remains unchanged. This is an agent-facing projection only.
    """
    extra = {str(x).strip() for x in (extra_fields or ())} if extra_fields else set()
    if isinstance(value, list):
        return [
            compact_result(v, max_text_chars=max_text_chars, max_evidence=max_evidence, extra_fields=extra)
            for v in value[:50]
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
        data["text"] = data["text"][:max_text_chars] + "\n[... compact MCP projection ...]"

    # Command output is aggressively bounded because full stdout/stderr is artifact-backed.
    if isinstance(data.get("summary"), str) and len(data["summary"]) > max_text_chars:
        data["summary"] = data["summary"][:max_text_chars] + "\n[... summary truncated ...]"
    stream_budget = max(256, max_text_chars // 3)
    if isinstance(data.get("stdout"), str) and len(data["stdout"]) > stream_budget:
        data["stdout"] = data["stdout"][:stream_budget] + "\n[... stdout truncated; use artifact ...]"
    if isinstance(data.get("stderr"), str) and len(data["stderr"]) > stream_budget:
        data["stderr"] = data["stderr"][-stream_budget:]
        data["stderr"] = "[... stderr head omitted; use artifact ...]\n" + data["stderr"]

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
        for item in data["results"][:50]:
            if isinstance(item, dict):
                item = compact_result(item, max_text_chars=min(max_text_chars, 1100), max_evidence=max_evidence, extra_fields=extra)
            new_results.append(item)
        data["results"] = new_results

    # Tool responses can wrap service payloads under arbitrary keys (for example
    # structured/canonical/content). Compact nested containers too; otherwise a
    # large inner model or command response bypasses the top-level limits.
    for key, item in list(data.items()):
        if key in {"results", "repo_context"}:
            continue
        if isinstance(item, (dict, list)):
            data[key] = compact_result(item, max_text_chars=max_text_chars, max_evidence=max_evidence, extra_fields=extra)

    for key in ("output", "content", "raw", "preview"):
        if isinstance(data.get(key), str) and len(data[key]) > max_text_chars:
            data[key] = data[key][:max_text_chars] + "\n[... compact MCP projection ...]"

    return data
