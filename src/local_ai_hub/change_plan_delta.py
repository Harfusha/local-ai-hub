"""Derived change-plan baselines. Reuse metadata, never verification authority."""
from __future__ import annotations

import re
from typing import Any

from .change_atoms import identity
from .change_plan_projection import project_change_plan

_HEX = re.compile(r"[0-9a-f]{64}")
_MAX_GROUPS = 256


def _snapshot(result: dict[str, Any]) -> dict[str, dict[str, str]] | None:
    if (
        result.get("success") is not True or result.get("git_visible_observation_complete") is not True
        or result.get("comparison") is not None or result.get("inventory_scope") != "git_visible_changes"
    ):
        return None
    groups = result.get("clusters", [])
    if not isinstance(groups, list) or len(groups) > _MAX_GROUPS:
        return None
    output = {}
    for group in groups:
        key, atoms = group.get("group_key"), group.get("observed_atom_ids")
        if (
            not isinstance(key, str) or not _HEX.fullmatch(key) or key in output
            or not isinstance(atoms, list) or not atoms
            or any(not isinstance(a, str) or not _HEX.fullmatch(a) for a in atoms)
        ):
            return None
        output[key] = identity("group-observation-v1", *sorted(atoms))
    # A group's own atom identity does not cover changed prerequisites.
    # Hash its reachable candidate graph as well, including cycles and
    # unresolved keys. This is only observed dependency context, not proof.
    edges: dict[str, list[str]] = {}
    for group in groups:
        key = group["group_key"]
        deps = group.get("dependency_group_candidates", [])
        if not isinstance(deps, list) or len(deps) > _MAX_GROUPS or any(
            not isinstance(dep, str) or not _HEX.fullmatch(dep) for dep in deps
        ):
            return None
        edges[key] = sorted(set(deps))
    snapshot = {}
    for key, digest in output.items():
        reached: set[str] = set()
        pending = [key]
        while pending:
            candidate = pending.pop()
            if candidate in reached:
                continue
            reached.add(candidate)
            pending.extend(edges.get(candidate, []))
        dependency_digest = identity(
            "group-dependency-context-v2",
            *[identity("dependency-node-v1", node, output.get(node, "unresolved"), *edges.get(node, []))
              for node in sorted(reached)],
        )
        snapshot[key] = {"content": digest, "dependencies": dependency_digest}
    return snapshot


def _key(root: str, revision: str) -> str:
    return identity("change-plan-baseline-v2", root, revision)


def remember_baseline(result: dict[str, Any], cache: Any) -> bool:
    revision = result.get("observed_change_set_id")
    root = result.get("root")
    snapshot = _snapshot(result)
    if cache is None or snapshot is None or not isinstance(root, str) or not isinstance(revision, str) or not _HEX.fullmatch(revision):
        return False
    try:
        cache.set(_key(root, revision), {"schema": 2, "groups": snapshot})
        return True
    except Exception:
        return False


def change_delta(result: dict[str, Any], cache: Any, previous: str | None, *, limit: int, offset: int) -> dict[str, Any]:
    if result.get("success") is not True:
        return result
    if not isinstance(previous, str) or not _HEX.fullmatch(previous):
        return {"success": False, "error": "Delta requires a prior observed revision"}
    current = _snapshot(result)
    if cache is None or current is None:
        return {"success": False, "error": "Complete current worktree observation and cache required"}
    try:
        stored = cache.get(_key(result["root"], previous))
    except Exception:
        stored = None
    old = stored.get("groups") if isinstance(stored, dict) and stored.get("schema") == 2 else None
    if (
        not isinstance(old, dict) or len(old) > _MAX_GROUPS
        or any(not isinstance(k, str) or not _HEX.fullmatch(k) or not isinstance(v, dict)
               or set(v) != {"content", "dependencies"}
               or any(not isinstance(digest, str) or not _HEX.fullmatch(digest) for digest in v.values())
               for k, v in old.items())
    ):
        return {"success": False, "error": "Prior baseline unavailable or invalid; refresh the full summary"}
    changed = {key for key, digest in current.items() if old.get(key) != digest}
    removed = sorted(set(old) - set(current))
    content_changed = {key for key, value in current.items() if old.get(key, {}).get("content") != value["content"]}
    dependency_only = changed - content_changed
    unchanged = len(current) - len(content_changed)
    delta = dict(result)
    delta["clusters"] = [g for g in result["clusters"] if g["group_key"] in changed]
    delta["cluster_count"] = len(delta["clusters"])
    # Task and verification metadata can change independently. A dependency
    # context match is not a review or verification receipt.
    output = project_change_plan(delta, mode="summary", limit=limit, offset=offset)
    output.update({
        "projection_mode": "delta",
        "previous_observed_change_set_id": previous,
        "changed_group_count": len(changed),
        "content_changed_group_count": len(content_changed),
        "dependency_context_only_changed_group_count": len(dependency_only),
        "unchanged_content_group_count": unchanged,
        "removed_group_count": len(removed),
        "removed_group_keys": removed[:16],
        "removed_group_keys_omitted": max(0, len(removed) - 16),
        "baseline_stored": remember_baseline(result, cache),
        "verification_status": "unknown",
        "commit_ready": False,
    })
    return output
