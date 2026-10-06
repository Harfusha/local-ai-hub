from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .agent_context import CompiledContext, ContextRequest
from .context_identity import (
    ContextPathHint,
    ContextPathHintInput,
    combine_settings_digests,
    normalize_context_path_hints,
    normalize_settings_digest,
)
from .evidence_contract import evidence_meta


class _ProjectContextInput(Protocol):
    root: Any
    settings: Any
    config_digest: str

    def path_hints(
        self, *, purpose: str, scope: str, repository_revision: str
    ) -> tuple[Any, ...]: ...


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


def build_context_request(
    payload: Mapping[str, Any],
    *,
    tenant: str = "",
    identity: str = "",
    trusted_path_hints: list[ContextPathHintInput] | tuple[ContextPathHintInput, ...] | None = (),
    settings_digest: str | None = None,
    project_context: _ProjectContextInput | None = None,
) -> ContextRequest:
    """Build request from task fields plus explicitly trusted project context."""
    repository_revision = _bounded_text(payload.get("repository_revision"), 200)
    repo_revision = _bounded_text(payload.get("repo_revision") or repository_revision, 200)
    request_root = _bounded_text(payload.get("root"), 1000)
    request_hints = normalize_context_path_hints(trusted_path_hints)
    effective_settings_digest = normalize_settings_digest(settings_digest)
    if project_context is not None:
        project_root = _resolved_project_root(project_context.root)
        if request_root:
            supplied_root = _resolved_project_root(request_root)
            if supplied_root != project_root:
                raise ValueError("project context root does not match request root")
        request_root = str(project_root)
        project_digest = normalize_settings_digest(project_context.config_digest)
        if project_digest is None:
            raise ValueError("project context settings digest is invalid")
        pinned_hints, entry_hints, saved_hints = _project_context_hint_groups(
            project_context,
            project_root=project_root,
            repository_revision=repo_revision,
            config_digest=project_digest,
        )
        rooted_request_hints = tuple(
            {
                **hint,
                "path": _relative_project_hint(hint["path"], project_root, strict=False),
            }
            for hint in request_hints
        )
        request_hints = normalize_context_path_hints(
            (*pinned_hints, *entry_hints, *rooted_request_hints, *saved_hints)
        )
        effective_settings_digest = combine_settings_digests(
            effective_settings_digest,
            project_digest,
        )
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
        root=request_root,
        tenant=_bounded_text(tenant, 200),
        identity=_bounded_text(identity, 200),
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
        settings_digest=effective_settings_digest,
        path_hints=request_hints,
    )


def _resolved_project_root(value: Any) -> Path:
    try:
        root = Path(value).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("project context root is invalid")
        return root
    except (OSError, RuntimeError, TypeError) as exc:
        raise ValueError("project context root is invalid") from exc


def _relative_project_hint(value: Any, root: Path, *, strict: bool) -> str:
    try:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved = candidate.resolve(strict=strict)
        if not resolved.is_relative_to(root):
            raise ValueError("project context hint escapes root")
        return resolved.relative_to(root).as_posix()
    except (OSError, RuntimeError, TypeError) as exc:
        raise ValueError("project context hint is invalid") from exc


def _project_context_hint_groups(
    project_context: _ProjectContextInput,
    *,
    project_root: Path,
    repository_revision: str,
    config_digest: str,
) -> tuple[tuple[ContextPathHint, ...], tuple[ContextPathHint, ...], tuple[ContextPathHint, ...]]:
    try:
        from .project_config import resolve_entry_points, resolve_pinned_context
    except ImportError as exc:
        raise RuntimeError("T21 project context API is unavailable") from exc

    settings = project_context.settings

    def configured(paths: Any, source: str) -> tuple[ContextPathHint, ...]:
        result: list[ContextPathHint] = []
        for path in paths:
            relative = _relative_project_hint(path, project_root, strict=True)
            result.append(
                {
                    "path": relative,
                    "purpose": "repository_search",
                    "scope": "task",
                    "provenance": f"project_config:{source}",
                    "repository_revision": repository_revision,
                    "config_digest": config_digest,
                }
            )
        return tuple(result)

    pinned = configured(resolve_pinned_context(project_root, settings), "pinned_context")
    entry_points = configured(resolve_entry_points(project_root, settings), "entry_point")
    saved: list[ContextPathHint] = []
    for record in project_context.path_hints(
        purpose="repository_search",
        scope="task",
        repository_revision=repository_revision,
    ):
        if not _project_hint_expiry_is_current(getattr(record, "expires_at", None)):
            continue
        raw_path = getattr(record, "path", None)
        if not isinstance(raw_path, str):
            raise ValueError("saved project path hint is invalid")
        hint: ContextPathHint = {
            "path": _relative_project_hint(raw_path, project_root, strict=False)
        }
        for field in ("purpose", "scope", "evidence_id", "provenance", "repository_revision", "config_digest", "expires_at"):
            field_value = getattr(record, field, None)
            if field_value is None:
                continue
            if not isinstance(field_value, str):
                raise ValueError(f"saved project path hint {field} is invalid")
            hint[field] = field_value
        if hint.get("purpose") not in (None, "repository_search"):
            continue
        if hint.get("scope") not in (None, "task"):
            continue
        if hint.get("repository_revision") not in (None, repository_revision):
            continue
        if hint.get("config_digest") not in (None, config_digest):
            continue
        saved.append(hint)
    return pinned, entry_points, tuple(saved)


def _project_hint_expiry_is_current(value: Any) -> bool:
    """Fail closed on invalid or expired metadata from non-provider callers."""
    if value is None:
        return True
    if not isinstance(value, str) or not value or len(value) > 64 or not value.isprintable():
        return False
    try:
        expires = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) < expires


def _repository_projection(repository: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "success", "context", "text", "evidence", "evidence_ids", "warnings",
        "repo_revision", "repository_revision", "changed_paths", "stale",
        "degraded", "degraded_reason", "terminal", "retryable", "error",
        "stop_code",
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
