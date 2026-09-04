from __future__ import annotations

import copy
from typing import Any


def compact_result(value: Any, *, max_text_chars: int = 1800, max_evidence: int = 10) -> Any:
    """Remove low-value runtime detail before an MCP result enters cloud context.

    The full hub HTTP API remains unchanged. This is an agent-facing projection only.
    """
    if isinstance(value, list):
        return [compact_result(v, max_text_chars=max_text_chars, max_evidence=max_evidence) for v in value[:50]]
    if not isinstance(value, dict):
        return value

    data = copy.deepcopy(value)
    # Low-level Ollama timing/counter fields belong in telemetry, not every tool result.
    for key in (
        "load_duration_ns", "eval_count", "prompt_eval_count", "total_duration_ns",
        "job_id", "prompt_budget",
    ):
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
                item = compact_result(item, max_text_chars=min(max_text_chars, 1100), max_evidence=max_evidence)
            new_results.append(item)
        data["results"] = new_results

    return data
