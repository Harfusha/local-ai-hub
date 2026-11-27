"""Derived change-plan baselines. Reuse metadata, never verification authority."""
from __future__ import annotations

import json
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
    # Precompute each node digest once; hashing every outgoing edge again
    # for every transitive consumer was cubic in dense candidate graphs.
    node_digests = {
        node: identity("dependency-node-v1", node, output.get(node, "unresolved"), *edges.get(node, []))
        for node in set(output) | {dep for deps in edges.values() for dep in deps}
    }
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
            *[node_digests[node] for node in sorted(reached)],
        )
        try:
            evidence_digest = _review_verification_digest(group)
        except (TypeError, ValueError, OverflowError):
            return None
        snapshot[key] = {
            "content": digest,
            "dependencies": dependency_digest,
            "review_verification": evidence_digest,
        }
    return snapshot


def _review_verification_digest(group: dict[str, Any]) -> str:
    """Fingerprint only currently exposed review and verification evidence."""
    fields = (
        "verification_status", "review_status", "review_evidence",
        "verification_evidence", "risks", "task_candidates", "local_ledger",
    )
    evidence = {field: group[field] for field in fields if field in group}
    canonical = json.dumps(evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return identity("group-review-verification-v1", canonical)


def _key(root: str, revision: str) -> str:
    return identity("change-plan-baseline-v3", root, revision)


def _continuation_revision(
    result: dict[str, Any], previous: str, current: dict[str, dict[str, str]],
    old: dict[str, dict[str, str]],
) -> str:
    parts = [
        str(result.get("observed_change_set_id", "")), previous,
    ]
    for label, snapshot in (("current", current), ("previous", old)):
        parts.append(label)
        for key, values in sorted(snapshot.items()):
            parts.extend((key, values["content"], values["dependencies"], values["review_verification"]))
    return identity("change-delta-continuation-v1", *parts)


def remember_baseline(result: dict[str, Any], cache: Any) -> bool:
    revision = result.get("observed_change_set_id")
    root = result.get("root")
    snapshot = _snapshot(result)
    if cache is None or snapshot is None or not isinstance(root, str) or not isinstance(revision, str) or not _HEX.fullmatch(revision):
        return False
    try:
        cache.set(_key(root, revision), {"schema": 3, "groups": snapshot})
        return True
    except Exception:
        return False


def change_delta(
    result: dict[str, Any], cache: Any, previous: str | None, *, limit: int, offset: int,
    continuation_revision: str | None = None,
) -> dict[str, Any]:
    if result.get("success") is not True:
        return result
    revision = result.get("observed_change_set_id")
    if not isinstance(revision, str) or not _HEX.fullmatch(revision):
        return {"success": False, "error": "Current observation revision unavailable; refresh the full summary"}
    if not isinstance(previous, str) or not _HEX.fullmatch(previous):
        return {"success": False, "error": "Delta requires a prior observed revision"}
    current = _snapshot(result)
    if cache is None or current is None:
        return {"success": False, "error": "Complete current worktree observation and cache required"}
    try:
        stored = cache.get(_key(result["root"], previous))
    except Exception:
        stored = None
    old = stored.get("groups") if isinstance(stored, dict) and stored.get("schema") == 3 else None
    if (
        not isinstance(old, dict) or len(old) > _MAX_GROUPS
        or any(not isinstance(k, str) or not _HEX.fullmatch(k) or not isinstance(v, dict)
               or set(v) != {"content", "dependencies", "review_verification"}
               or any(not isinstance(digest, str) or not _HEX.fullmatch(digest) for digest in v.values())
               for k, v in old.items())
    ):
        return {"success": False, "error": "Prior baseline unavailable or invalid; refresh the full summary"}
    page_revision = _continuation_revision(result, previous, current, old)
    if offset > 0 and continuation_revision != page_revision:
        return {
            "success": False,
            "error": "Delta continuation is missing or stale; restart from offset 0 with the same prior revision",
            "restart_required": True,
            "commit_ready": False,
        }
    if offset == 0 and continuation_revision is not None and continuation_revision != page_revision:
        return {"success": False, "error": "Delta continuation revision does not match the current observation",
                "restart_required": True, "commit_ready": False}
    changed = {
        key for key, value in current.items()
        if old.get(key, {}).get("content") != value["content"]
        or old.get(key, {}).get("dependencies") != value["dependencies"]
    }
    removed = sorted(set(old) - set(current))
    content_changed = {key for key, value in current.items() if old.get(key, {}).get("content") != value["content"]}
    dependency_only = {
        key for key in changed - content_changed
        if old.get(key, {}).get("dependencies") != current[key]["dependencies"]
    }
    review_verification_changed = {
        key for key, value in current.items()
        if old.get(key, {}).get("review_verification") != value["review_verification"]
    }
    unchanged = len(current) - len(content_changed)
    delta = dict(result)
    updated = changed | review_verification_changed
    delta["clusters"] = [g for g in result["clusters"] if g["group_key"] in updated]
    delta["cluster_count"] = len(delta["clusters"])
    # Task and verification metadata can change independently. A dependency
    # context match is not a review or verification receipt.
    output = project_change_plan(delta, mode="summary", limit=limit, offset=offset)
    # Both inventories use the same page cursor, including deletion-only deltas.
    removed_page = removed[offset:offset + limit]
    has_more = offset + limit < max(len(updated), len(removed))
    final_page = not has_more
    output.update({
        "projection_mode": "delta",
        "has_more": has_more,
        "next_offset": offset + limit if has_more else None,
        "continuation_revision": page_revision if has_more else None,
        "previous_observed_change_set_id": previous,
        "changed_group_count": len(changed),
        "updated_group_count": len(updated),
        "content_changed_group_count": len(content_changed),
        "dependency_context_only_changed_group_count": len(dependency_only),
        "review_verification_changed_group_count": len(review_verification_changed),
        "unchanged_content_group_count": unchanged,
        "removed_group_count": len(removed),
        "removed_group_keys": removed_page,
        "removed_group_keys_omitted": len(removed) - len(removed_page),
        "removed_group_offset": offset,
        # Preserve the previous baseline until all pages from this snapshot
        # have been delivered. If a caller stops early, repeating a delta may
        # duplicate evidence, but cannot silently skip it.
        "baseline_stored": remember_baseline(result, cache) if final_page else False,
        "verification_status": "unknown",
        "commit_ready": False,
    })
    return output
