"""Read-only checkout synchronization diagnostics for Git-owned project state.

Do not fetch, merge, commit, stash, or report a remote as current. A Git status
is an observation of one checkout, not authorization or verified project truth.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from .process_utils import clean_git_env, hidden_run_kwargs
from .repo_plan.storage import get_git_context

_PATHS = (
    ".local-ai-hub/project.json", ".local-ai-hub/knowledge",
    ".local-ai-hub/agent-os", ".local-ai-hub/plans",
    ".local-ai-hub/specs", ".local-ai-hub/decisions", ".local-ai.toml",
    ".local-ai-hub/.gitignore",
)
_MAX_OUTPUT = 256 * 1024
_MAX_ENTRIES = 256


def _git(root: Path, *args: str) -> bytes | None:
    """Use Git without refreshing the index or running fsmonitor hooks."""
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false",
             "-C", str(root), *args],
            capture_output=True, timeout=5,
            env=clean_git_env(), **hidden_run_kwargs(),
        )
        if result.returncode or len(result.stdout) > _MAX_OUTPUT:
            return None
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        return None


def _conflict_summary(root: Path, path: str) -> dict[str, Any]:
    """Compare validated index stages, not conflicted working-tree text.

    Only return field names; never expose unreviewed stage values or resolve
    an index conflict. Even disjoint edits remain operator review candidates.
    """
    from .repo_knowledge import _MAX_BYTES, validate_knowledge_file
    from .repo_plan.schema_validation import RepoPlanValidationError

    if not path.startswith(".local-ai-hub/knowledge/") or not path.endswith(".json"):
        return {"classification": "manual_review_required"}
    raw = _git(root, "ls-files", "-u", "-z", "--", ":(literal)" + path)
    if raw is None:
        return {"classification": "unavailable"}
    stages: dict[int, str] = {}
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        meta, separator, name = entry.partition(b"\t")
        fields = meta.split()
        if (
            not separator or name != path.encode("utf-8") or len(fields) != 3
            or fields[0] not in {b"100644", b"100755"}
            or not re.fullmatch(rb"(?:[0-9a-f]{40}|[0-9a-f]{64})", fields[1])
            or fields[2] not in {b"1", b"2", b"3"}
        ):
            return {"classification": "manual_review_required"}
        stages[int(fields[2])] = fields[1].decode("ascii")
    if set(stages) != {1, 2, 3}:
        return {"classification": "add_delete_or_missing_stage"}
    records = []
    for stage in (1, 2, 3):
        size = _git(root, "cat-file", "-s", stages[stage])
        if size is None or not size.strip().isdigit() or int(size) > _MAX_BYTES:
            return {"classification": "invalid_or_unavailable_stage"}
        data = _git(root, "cat-file", "blob", stages[stage])
        if data is None:
            return {"classification": "invalid_or_unavailable_stage"}
        try:
            records.append(validate_knowledge_file(path, data))
        except (RepoPlanValidationError, ValueError, TypeError):
            return {"classification": "invalid_or_unavailable_stage"}
    if _git(root, "ls-files", "-u", "-z", "--", ":(literal)" + path) != raw:
        return {"classification": "changed_during_read"}
    base, ours, theirs = records
    identity = ("schema_version", "project_id", "kind", "id")
    if any(ours[key] != base[key] or theirs[key] != base[key] for key in identity):
        return {"classification": "identity_or_schema_conflict"}
    if base["kind"] in {"review", "finding"}:
        return {"classification": "manual_review_required"}
    # Keep semantically coupled fields (claim, evidence and provenance) as
    # atomic groups. Only a title change is independent of declaration content.
    groups = {
        "title": lambda row: row["payload"]["title"],
        "declaration": lambda row: (
            {k: v for k, v in row["payload"].items() if k != "title"},
            row["provenance"], row["evidence"], row["relations"],
        ),
    }
    ours_changed = [key for key, get in groups.items() if get(ours) != get(base)]
    theirs_changed = [key for key, get in groups.items() if get(theirs) != get(base)]
    conflicting = [
        key for key, get in groups.items()
        if key in ours_changed and key in theirs_changed and get(ours) != get(theirs)
    ]
    return {
        "classification": (
            "divergent_semantic_edit" if conflicting else
            "identical_edit" if ours == theirs else
            "nondivergent_edit_candidate"
        ),
        "ours_changed_groups": ours_changed,
        "theirs_changed_groups": theirs_changed,
        "conflicting_groups": conflicting,
        "requires_review": True,
    }

def checkout_sync_status(root: Path) -> dict[str, Any]:
    """Report shared-state Git changes; never expose local journal contents."""
    if not (root / ".git").exists():
        return {"state": "not_git_checkout", "complete": False}
    branch, head = get_git_context(root)
    raw = _git(root, "status", "--porcelain=v1", "-z", "--no-renames",
               "--untracked-files=all", "--ignored=matching", "--", *_PATHS)
    local_tracked = _git(root, "ls-files", "-z", "--", ".local-ai-hub/local")
    if raw is None or local_tracked is None:
        return {"state": "unavailable", "complete": False}
    entries: list[dict[str, str]] = []
    complete = True
    for field in raw.split(b"\0"):
        if not field:
            continue
        if len(field) < 4 or field[2:3] != b" ":
            complete = False
            continue
        if len(entries) == _MAX_ENTRIES:
            complete = False
            break
        try:
            code = field[:2].decode("ascii")
            path = field[3:].decode("utf-8")
        except UnicodeError:
            complete = False
            continue
        if any(not char.isprintable() for char in path) or not any(
            path == prefix or path.startswith(prefix + "/") for prefix in _PATHS
        ):
            complete = False
            continue
        kind = (
            "conflict" if code in {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}
            else "untracked" if code == "??"
            else "ignored" if code == "!!"
            else "modified"
        )
        entries.append({"path": path, "index_worktree_status": code, "state": kind})
    conflict_entries = [item for item in entries if item["state"] == "conflict"]
    conflict_summaries = [
        {"path": item["path"], **_conflict_summary(root, item["path"])}
        for item in conflict_entries[:8]
    ]
    upstream = _git(root, "rev-list", "--left-right", "--count", "HEAD...@{upstream}")
    divergence: dict[str, Any] = {"status": "unknown_or_no_upstream"}
    if upstream is not None:
        parts = upstream.split()
        if len(parts) == 2 and all(part.isdigit() for part in parts):
            divergence = {"status": "local_tracking_ref_only", "ahead": int(parts[0]), "behind": int(parts[1])}
    if get_git_context(root) != (branch, head):
        return {"state": "changed_during_read", "complete": False}
    # Ignored shareable files cannot silently count as synchronized.
    state = (
        "conflict" if any(item["state"] == "conflict" for item in entries)
        else "unsafe_local_tracking" if local_tracked
        else "partial" if not complete
        else "local_changes" if entries
        else "clean_shared_paths"
    )
    return {
        "state": state, "complete": complete, "branch": branch, "head": head,
        "entries": entries, "tracked_local_state": bool(local_tracked),
        "conflicts": conflict_summaries, "conflicts_truncated": len(conflict_entries) > 8,
        "divergence": divergence, "remote_verified": False,
    }
