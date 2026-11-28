from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import uuid

_GIT_PROJECT_ID_KEY = "local-ai-hub.project-id"


def read_git_project_id(repo_root: str | Path) -> str | None:
    root = Path(repo_root).expanduser().resolve(strict=True)
    git_marker = root / ".git"
    if not git_marker.exists() and not git_marker.is_symlink():
        return None
    from .process_utils import clean_git_env, hidden_run_kwargs

    try:
        result = subprocess.run(
            ["git", "-C", str(root), "config", "--local", "--get", _GIT_PROJECT_ID_KEY],
            capture_output=True, text=True, timeout=2.0, env=clean_git_env(), **hidden_run_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("Git project identity could not be read") from exc
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        raise ValueError("Git project identity could not be read")
    try:
        project_id = result.stdout.strip()
        if str(uuid.UUID(project_id)) != project_id.lower():
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError("Git project identity is invalid") from exc
    return project_id.lower()


def persist_git_project_id(repo_root: str | Path, project_id: str) -> None:
    root = Path(repo_root).expanduser().resolve(strict=True)
    git_marker = root / ".git"
    if not git_marker.exists() and not git_marker.is_symlink():
        return
    try:
        canonical_id = str(uuid.UUID(project_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("project_id must be a UUID") from exc
    if project_id.lower() != canonical_id:
        raise ValueError("project_id must be a canonical UUID")
    existing = read_git_project_id(root)
    if existing is not None:
        if existing != canonical_id:
            raise ValueError("Git project identity conflicts with project manifest")
        return
    from .process_utils import clean_git_env, hidden_run_kwargs

    try:
        result = subprocess.run(
            ["git", "-C", str(root), "config", "--local", "--replace-all", _GIT_PROJECT_ID_KEY, canonical_id],
            capture_output=True, text=True, timeout=2.0, env=clean_git_env(), **hidden_run_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("Git project identity could not be saved") from exc
    if result.returncode != 0 or read_git_project_id(root) != canonical_id:
        raise ValueError("Git project identity could not be saved")

def project_scope_id(repo_root: str | Path) -> str:
    """Return the stable manifest identity; non-project workspaces stay path-local."""
    root = Path(repo_root).expanduser().resolve(strict=True)
    manifest_path = root / ".local-ai-hub" / "project.json"
    if manifest_path.is_symlink():
        raise ValueError("project manifest must not be a symlink")
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            project_id = manifest["project_id"]
            if (
                not isinstance(manifest, dict)
                or manifest.get("schema_version") != 1
                or not isinstance(project_id, str)
                or str(uuid.UUID(project_id)) != project_id.lower()
            ):
                raise ValueError
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError("project manifest has no valid stable project_id") from exc
        git_project_id = read_git_project_id(root)
        if git_project_id is not None and git_project_id != project_id:
            raise ValueError("Git project identity conflicts with project manifest")
        return project_id
    # A Git checkout must be enrolled by the one-time update migration before
    # project-scoped state can be read or written. A path-derived identity here
    # silently splits one repository into different projects after relocation.
    git_marker = root / ".git"
    if git_marker.exists() or git_marker.is_symlink():
        project_id = read_git_project_id(root)
        if project_id is not None:
            return project_id
        raise ValueError("Git checkout has no migrated stable project_id")
    local_key = str(root).casefold().encode("utf-8")
    return f"local:{hashlib.sha256(local_key).hexdigest()}"


def worktree_scope_id(repo_root: str | Path) -> str:
    """Return a local-only scope for runtime work tied to one checkout path."""
    root = Path(repo_root).expanduser().resolve(strict=True)
    return hashlib.sha256(str(root).casefold().encode("utf-8")).hexdigest()


def repository_snapshot_id(repo_root: str | Path) -> str:
    """Return a local fence identity for the current Git branch and HEAD."""
    root = Path(repo_root).expanduser().resolve(strict=True)
    from .repo_knowledge import _git_checkout_generation

    generation = _git_checkout_generation(root)
    # HEAD is the repository content snapshot. Branch and worktree paths are
    # tracked separately for projection refresh and local ownership.
    revision = generation[2] if generation is not None else None
    encoded = json.dumps(revision, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
