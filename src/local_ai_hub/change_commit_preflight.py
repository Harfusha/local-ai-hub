"""Read-only commit scope preflight. Never mutate Git or authorize execution."""
from __future__ import annotations

import re
from typing import Any

_REVISION = re.compile(r"[a-f0-9]{64}")
_MAX_SELECTION = 64


def revision_error(result: dict[str, Any], expected: str | None) -> str | None:
    if expected is None:
        return None
    if not isinstance(expected, str) or not _REVISION.fullmatch(expected):
        return "Invalid expected change-set revision"
    if result.get("observed_change_set_id") != expected:
        return "Observed changes differ from the expected revision; refresh the plan"
    if result.get("git_visible_observation_complete") is not True:
        return "Cannot confirm an incomplete change-set revision; inspect unresolved scopes"
    return None


def commit_preflight(result: dict[str, Any], paths: list[str] | None, expected: str | None) -> dict[str, Any]:
    if result.get("success") is not True:
        return result
    if result.get("comparison") is not None:
        return {"success": False, "error": "Commit preflight requires a working tree"}
    if expected is None:
        return {"success": False, "error": "Commit preflight requires expected_revision from a complete change plan"}
    error = revision_error(result, expected)
    if error:
        return {"success": False, "error": error, "commit_ready": False}
    if (
        not isinstance(paths, list) or not 1 <= len(paths) <= _MAX_SELECTION
        or any(not isinstance(path, str) or not path for path in paths)
        or len(set(paths)) != len(paths)
    ):
        return {"success": False, "error": "Supply 1–64 distinct, exact changed paths"}
    inventory = {
        change["path"]: change for group in result.get("clusters", [])
        for change in group.get("changes", [])
    }
    selection = set(paths)
    if not selection <= inventory.keys():
        return {"success": False, "error": "Selection contains paths absent from the change plan"}
    outside_staged = sorted(
        path for path, change in inventory.items() if path not in selection
        and change["status"] != "??" and change["status"][0] != " "
    )
    blockers = []
    to_stage = []
    staged = []
    if outside_staged:
        blockers.append("unselected_staged_changes")
    for path, change in sorted(inventory.items()):
        status = change["status"]
        if status in {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}:
            if "unmerged_changes" not in blockers:
                blockers.append("unmerged_changes")
        if path not in selection:
            continue
        if status == "??":
            # A raw untracked content observation is not a prospective index
            # blob: attributes, filters and executable bits may change it.
            if "untracked_requires_explicit_review" not in blockers:
                blockers.append("untracked_requires_explicit_review")
        elif status[0] != " " and status[1] != " ":
            if "mixed_staged_unstaged_selection" not in blockers:
                blockers.append("mixed_staged_unstaged_selection")
        elif status[0] != " ":
            staged.append(path)
        elif status[1] != " ":
            to_stage.append(path)
    selected_groups = [
        group for group in result.get("clusters", [])
        if selection.intersection(group.get("files", []))
    ]
    cut_groups = [
        group["group_key"] for group in selected_groups
        if not set(group["files"]) <= selection
    ]
    if cut_groups:
        blockers.append("partial_proposed_group")
    group_keys = {group["group_key"] for group in selected_groups}
    pending_dependencies = sorted({
        key for group in selected_groups for key in group.get("dependency_group_candidates", [])
        if key not in group_keys
    })
    if pending_dependencies:
        blockers.append("unselected_dependency_candidates")
    if any("dependency_cycle_or_blocked" in group.get("risks", []) for group in selected_groups):
        blockers.append("dependency_cycle_or_blocked")
    exact_index = not blockers and not to_stage and set(staged) == selection
    metadata = result.get("git_snapshot_metadata") or {}
    prospective_tree = metadata.get("index_tree_oid") if exact_index else None
    return {
        "success": True,
        "prospective_index_tree_oid": prospective_tree or None,
        "prospective_tree_status": "observed_index_only" if prospective_tree else "unavailable",
        "observed_change_set_id": expected,
        "selected_paths": sorted(selection),
        "already_staged": staged,
        "unstaged_selection": to_stage,
        "outside_staged_count": len(outside_staged),
        "outside_staged_paths": outside_staged[:16],
        "outside_staged_omitted": max(0, len(outside_staged) - 16),
        "blockers": blockers,
        "selection_matches_observation": True,
        "staging_preview_available": not blockers,
        "stage_argv_preview": ["git", "--literal-pathspecs", "add", "--", *to_stage] if to_stage and not blockers else [],
        "index_scope_matches_selection": exact_index,
        "candidate_dependency_count": len(pending_dependencies),
        "verification_status": "unknown",
        "commit_ready": False,
        "requires_explicit_approval": True,
        "requires_post_stage_reinspection": True,
        "limitations": [
            "No Git mutation, authorization, ownership, or dependency proof.",
            "Preview is advisory; re-observe immediately before staging and inspect the exact staged scope afterwards.",
            "Independent validation of the prospective commit tree and required checks is still necessary.",
        ],
    }
