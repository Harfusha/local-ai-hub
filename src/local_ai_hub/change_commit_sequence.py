"""Plan an exact staged commit sequence without writing Git objects."""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

from .change_index_tree import index_tree_oid

_MAX_STEPS = 16
_MAX_PATHS = 64
_MODES = {b"100644", b"100755", b"120000", b"160000"}


def _entries(raw: bytes, *, staged: bool) -> dict[bytes, tuple[bytes, bytes]]:
    if raw and not raw.endswith(b"\0"):
        raise ValueError("Incomplete tree inventory")
    entries = {}
    for row in raw.split(b"\0")[:-1]:
        meta, path = row.split(b"\t", 1)
        if staged:
            mode, oid, stage = meta.split(b" ")
            if stage != b"0":
                raise ValueError("Unmerged index")
        else:
            mode, kind, oid = meta.split(b" ")
            if kind not in {b"blob", b"commit"}:
                raise ValueError("Unsupported tree entry")
        if mode not in _MODES or not re.fullmatch(rb"[0-9a-f]{40}|[0-9a-f]{64}", oid) or path in entries:
            raise ValueError("Invalid tree entry")
        entries[path] = (mode, oid)
    return entries


def plan_sequence(parent_raw: bytes, index_raw: bytes, parent: str, expected_tree: str,
                  sequence: Any, groups: list[dict[str, Any]], revision: str) -> dict[str, Any]:
    if not isinstance(sequence, list) or not 1 <= len(sequence) <= _MAX_STEPS:
        raise ValueError("Supply 1–16 ordered commit groups")
    before = _entries(parent_raw, staged=False)
    target = _entries(index_raw, staged=True)
    changed = {p for p in set(before) | set(target) if before.get(p) != target.get(p)}
    seen: set[bytes] = set()
    owners: dict[str, int] = {}
    steps = []
    previous_tree = index_tree_oid(parent_raw_to_index(before), parent)
    if previous_tree is None:
        raise ValueError("Invalid parent tree")
    for number, step in enumerate(sequence):
        if not isinstance(step, dict) or set(step) != {"paths", "message"}:
            raise ValueError("Each step requires paths and message")
        paths, message = step["paths"], step["message"]
        if (not isinstance(paths, list) or not 1 <= len(paths) <= _MAX_PATHS
                or any(not isinstance(p, str) or not p or "\0" in p for p in paths)
                or len(set(paths)) != len(paths)
                or not isinstance(message, str) or not message.strip() or len(message) > 4096
                or any(ord(c) < 32 and c not in "\n\t" for c in message)):
            raise ValueError("Invalid sequence step")
        selected = {os.fsencode(p) for p in paths}
        if selected & seen or not selected <= changed or len(seen | selected) > _MAX_PATHS:
            raise ValueError("Sequence must partition exact staged paths")
        seen.update(selected)
        for path in paths:
            owners[path] = number
        for path in selected:
            if path in target:
                before[path] = target[path]
            else:
                before.pop(path, None)
        tree = index_tree_oid(parent_raw_to_index(before), parent)
        if tree is None or tree == previous_tree:
            raise ValueError("Invalid or empty intermediate tree")
        steps.append({"paths": sorted(paths), "message": message, "tree_oid": tree, "parent_tree_oid": previous_tree})
        previous_tree = tree
    if seen != changed or previous_tree != expected_tree:
        raise ValueError("Sequence does not cover the exact approved index")
    group_steps: dict[str, int] = {}
    for group in groups:
        files = set(group.get("files", []))
        selected = files & owners.keys()
        if not selected:
            continue
        positions = {owners[p] for p in selected}
        if selected != files or len(positions) != 1:
            raise ValueError("Sequence cuts a proposed logical group")
        group_steps[group["group_key"]] = next(iter(positions))
    for group in groups:
        key = group.get("group_key")
        if key not in group_steps:
            continue
        if any(dep not in group_steps or group_steps[dep] > group_steps[key]
               for dep in group.get("dependency_group_candidates", [])):
            raise ValueError("Sequence violates candidate dependency ordering")
    content = {"parent_oid": parent, "tree_oid": expected_tree, "observed_change_set_id": revision, "steps": steps}
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
    return {**content, "preview_digest": digest, "verification_status": "unknown", "commit_ready": False}


def parent_raw_to_index(entries: dict[bytes, tuple[bytes, bytes]]) -> bytes:
    return b"".join(mode + b" " + oid + b" 0\t" + path + b"\0"
                    for path, (mode, oid) in sorted(entries.items()))


def suggest_sequence(plan: dict[str, Any], expected_revision: str | None = None) -> dict[str, Any]:
    """Build an editable, read-only sequence proposal from the complete staged scope."""
    from .change_commit_preflight import commit_preflight

    if plan.get("success") is not True:
        return plan
    if plan.get("inventory_scope") != "git_visible_changes" or plan.get("comparison") is not None:
        return {"success": False, "error": "Complete working-tree inventory required"}
    revision = plan.get("observed_change_set_id")
    if expected_revision is not None and revision != expected_revision:
        return {"success": False, "error": "Observed revision changed; refresh the plan"}
    groups = plan.get("clusters", [])
    paths = sorted(change["path"] for group in groups for change in group["changes"]
                   if change["status"] != "??" and change["status"][0] != " ")
    if not paths:
        return {"success": False, "error": "No staged changes to propose"}
    preflight = commit_preflight(plan, paths, revision)
    if preflight.get("index_scope_matches_selection") is not True or not preflight.get("prospective_index_tree_oid"):
        return {"success": False, "error": "Staged selection requires review before sequence suggestion",
                "blockers": preflight.get("blockers", []), "commit_ready": False}
    selected = set(paths)
    by_key = {group["group_key"]: group for group in groups if selected.intersection(group["files"])}
    units = plan.get("dependency_plan", {}).get("candidate_commit_units", [])
    seen = set()
    sequence = []
    for unit in units:
        keys = [key for key in unit if key in by_key]
        if not keys:
            continue
        if len(keys) != len(unit) or seen.intersection(keys):
            return {"success": False, "error": "Incomplete dependency component"}
        seen.update(keys)
        members = [by_key[key] for key in keys]
        message = members[0].get("suggested_commit_message", "") if len(members) == 1 else "chore: update related components"
        if not isinstance(message, str) or not message.strip() or len(message) > 100 or any(ord(c) < 32 for c in message):
            message = "chore: update reviewed changes"
        sequence.append({"paths": sorted(path for group in members for path in group["files"]), "message": message})
    if seen != set(by_key) or not 1 <= len(sequence) <= _MAX_STEPS:
        return {"success": False, "error": "Dependency order unavailable or exceeds sequence step budget"}
    flattened = [path for step in sequence for path in step["paths"]]
    if sorted(flattened) != paths:
        return {"success": False, "error": "Proposal does not cover exact staged selection"}
    return {"success": True, "sequence": sequence, "selected_paths": paths,
            "observed_change_set_id": revision, "tree_oid": preflight["prospective_index_tree_oid"],
            "requires_explicit_review": True, "requires_sequence_preview": True,
            "verification_status": "unknown", "commit_ready": False}
