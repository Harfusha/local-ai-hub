from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from .agent_context import CompiledContext, ContextRequest
from .evidence_contract import evidence_meta


def _bounded_text(value: Any, limit: int) -> str:
    return str(value or "")[: max(0, limit)]


def _bounded_list(value: Any, limit: int = 64) -> tuple[str, ...]:
    if isinstance(value, str):
        value = (value,)
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if text and text not in seen:
            result.append(text[:240])
            seen.add(text)
        if len(result) >= limit:
            break
    return tuple(result)


def build_context_request(payload: Mapping[str, Any], *, tenant: str = "") -> ContextRequest:
    """Build one task-scoped request without dropping guarded fields."""
    repository_revision = _bounded_text(payload.get("repository_revision"), 200)
    repo_revision = _bounded_text(payload.get("repo_revision") or repository_revision, 200)
    raw_budget = payload.get("token_budget", 4000)
    try:
        token_budget = max(1, min(int(raw_budget or 4000), 128_000))
    except (TypeError, ValueError, OverflowError):
        token_budget = 4000
    return ContextRequest(
        task_id=_bounded_text(payload.get("task_id"), 200),
        token_budget=token_budget,
        include_kinds=_bounded_list(payload.get("include_kinds")),
        changed_paths=_bounded_list(payload.get("changed_paths"), 32),
        root=_bounded_text(payload.get("root"), 1000),
        tenant=_bounded_text(tenant, 200),
        include_diagnostics=bool(payload.get("include_diagnostics", False)),
        clone_id=_bounded_text(payload.get("clone_id"), 200),
        worktree_id=_bounded_text(payload.get("worktree_id"), 200),
        branch=_bounded_text(payload.get("branch"), 200),
        repository_id=_bounded_text(payload.get("repository_id"), 200),
        session_id=_bounded_text(payload.get("session_id"), 200),
        repository_revision=repository_revision,
        phase=_bounded_text(payload.get("phase"), 80),
        focus=_bounded_list(payload.get("focus"), 16),
        preload_profile=_bounded_text(payload.get("preload_profile"), 120),
        repo_revision=repo_revision,
        since_hash=_bounded_text(payload.get("since_hash") or payload.get("etag"), 120),
    )


def _repository_projection(repository: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "success", "context", "text", "evidence", "evidence_ids", "warnings",
        "repo_revision", "repository_revision", "changed_paths", "stale",
        "degraded", "degraded_reason", "terminal", "retryable", "error",
        "adaptive_context_pack", "context_pack", "context_id", "model_degraded",
        "model_degraded_reason", "requires_approval", "requires_override",
    }
    result: dict[str, Any] = {}
    for key in allowed:
        if key in repository:
            result[key] = repository[key]
    return result


def compose_task_context(
    *,
    task_id: str,
    compiled: CompiledContext,
    repository: Mapping[str, Any],
    token_budget: int,
    repository_required: bool = True,
) -> dict[str, Any]:
    """Compose Agent OS state and repository evidence into one bounded contract."""
    repo = _repository_projection(repository)
    repo_ok = bool(repo.get("success", False))
    # A task may be purely Agent-OS scoped (for example a coordination or
    # model-evaluation task without a checkout).  Such a request must still
    # receive the same durable task_context contract; absence of a repository
    # is only incomplete when the caller explicitly supplied one.
    repository_available = bool(repository_required and repo_ok)
    agent_text = compiled.text()
    repo_text = str(repo.get("text") or repo.get("context") or "")
    raw_text = "\n\n".join(part for part in (agent_text, repo_text) if part)
    max_chars = max(512, min(int(token_budget or 4000), 128_000) * 4)
    text = raw_text[:max_chars]
    truncated = len(text) < len(raw_text)

    evidence_ids = list(dict.fromkeys(
        [str(item) for item in (repo.get("evidence_ids") or ()) if str(item)]
        + [
            str(item.get("evidence_id"))
            for item in (repo.get("evidence") or ())
            if isinstance(item, Mapping) and item.get("evidence_id")
        ]
    ))[:64]
    repo_pack = repo.get("adaptive_context_pack") or repo.get("context_pack") or {}
    if isinstance(repo_pack, Mapping):
        evidence_ids.extend(str(item) for item in (repo_pack.get("evidence_ids") or ()) if str(item))
        evidence_ids = list(dict.fromkeys(evidence_ids))[:64]
    repo_revision = str(repo.get("repo_revision") or repo.get("repository_revision") or compiled.repo_revision or "")[:200]
    expected_revision = str(compiled.repo_revision or "")[:200]
    revision_mismatch = bool(expected_revision and repo_revision and expected_revision != repo_revision)
    repo_context_id = str(repo.get("context_id") or (repo_pack.get("context_id") if isinstance(repo_pack, Mapping) else ""))
    etag_input = f"{task_id}|{compiled.etag()}|{repo_context_id}|{repo_revision}|{','.join(evidence_ids)}"
    etag = hashlib.sha256(etag_input.encode("utf-8", "replace")).hexdigest()[:16]
    warnings = [dict(item) for item in compiled.warnings]
    warnings.extend(item for item in (repo.get("warnings") or ()) if isinstance(item, Mapping))
    if revision_mismatch:
        warnings.append({"code": "repository_revision_mismatch", "expected": expected_revision, "actual": repo_revision})
    complete = (repository_available or not repository_required) and not compiled.stale and not bool(repo.get("stale", False)) and not revision_mismatch
    provenance = evidence_meta(
        "task_context.repository",
        repo_revision,
        evidence_ids,
        bool(compiled.stale or repo.get("stale", False)),
        "success" if complete else ("stale" if compiled.stale or repo.get("stale", False) else "incomplete"),
    )
    return {
        "success": complete,
        "complete": complete,
        "partial": not complete,
        "task_id": _bounded_text(task_id, 200),
        "context_id": f"taskctx_{etag}",
        "etag": etag,
        "text": text,
        "estimated_tokens": max(1, len(text) // 4) if text else 0,
        "token_budget": int(token_budget or 4000),
        "truncated": truncated or compiled.truncated,
        "source_layers": ["agent_state", "repository"] if repository_required else ["agent_state"],
        "agent_state": compiled.to_dict(compact=True),
        "repository": repo,
        "repo_revision": repo_revision,
        "evidence_ids": evidence_ids,
        "provenance": provenance,
        "stale": bool(compiled.stale or repo.get("stale", False) or revision_mismatch),
        "warnings": warnings[:32],
        "repository_required": bool(repository_required),
        "omitted_sections": ["repository"] if repository_required and not repo_ok else [],
        "next_action": "refresh_repository_context" if repository_required and not repo_ok else "use_compiled_context",
    }
