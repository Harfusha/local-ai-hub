from __future__ import annotations

import hashlib
import json
from pathlib import Path
import uuid


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
        return project_id
    local_key = str(root).casefold().encode("utf-8")
    return f"local:{hashlib.sha256(local_key).hexdigest()}"


def worktree_scope_id(repo_root: str | Path) -> str:
    """Return a local-only scope for runtime work tied to one checkout path."""
    root = Path(repo_root).expanduser().resolve(strict=True)
    return hashlib.sha256(str(root).casefold().encode("utf-8")).hexdigest()
