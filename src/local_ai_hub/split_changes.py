"""Read-only, conservative change grouping for the existing split_changes action."""

from __future__ import annotations

import os
import re
from pathlib import PurePosixPath
from typing import Any

from .change_atoms import identity, inspect_change_atoms


def _component(path: str) -> tuple[str, str]:
    p = PurePosixPath(path)
    parts = p.parts
    stem = p.stem.lower()
    is_test = any(part.lower() in {"tests", "test", "spec", "__tests__"} for part in parts[:-1]) or bool(
        re.search(r"(^test_|_test$|[._-](?:test|spec)$)", stem)
    )
    stem = re.sub(r"^test_|_test$|[._-](?:test|spec)$", "", stem)
    stem = re.sub(r"(?:controller|service|repository|model|test)$", "", stem, flags=re.I)
    key = re.sub(r"[^a-z0-9]+", "", stem)
    if is_test:
        return key, "test"
    if p.suffix.lower() in {".md", ".rst", ".txt"} or "docs" in parts[:-1]:
        return key, "docs"
    if p.suffix.lower() in {".toml", ".json", ".yaml", ".yml", ".ini", ".cfg", ".lock"}:
        return key, "config"
    return key, "implementation"


def _parse_status(raw: bytes) -> dict[str, str]:
    if raw and not raw.endswith(b"\0"):
        raise ValueError("Incomplete Git status")
    result = {}
    for record in raw.split(b"\0")[:-1]:
        if len(record) < 4 or record[2:3] != b" ":
            raise ValueError("Malformed Git status")
        status = record[:2].decode("ascii")
        path = os.fsdecode(record[3:])
        if path in result or not path or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in path):
            raise ValueError("Unsupported or duplicate Git path")
        result[path] = status
    return result


def _parse_numstat(raw: bytes) -> dict[str, tuple[int | None, int | None]]:
    if raw and not raw.endswith(b"\0"):
        raise ValueError("Incomplete Git numstat")
    result = {}
    for record in raw.split(b"\0")[:-1]:
        fields = record.split(b"\t", 2)
        if len(fields) != 3 or not fields[2]:
            raise ValueError("Malformed Git numstat")
        a, d, path = fields
        result[os.fsdecode(path)] = (
            None if a == b"-" else int(a),
            None if d == b"-" else int(d),
        )
    return result


def _group(
    statuses: dict[str, str],
    staged: dict[str, tuple[int | None, int | None]],
    unstaged: dict[str, tuple[int | None, int | None]],
) -> list[dict[str, Any]]:
    # Exact normalized component names are only a heuristic. Do not merge
    # different production paths with the same basename or infer dependencies.
    components = {path: _component(path) for path in statuses}
    implementations: dict[str, list[str]] = {}
    for path, (key, role) in components.items():
        if key and role == "implementation" and statuses[path] != "??":
            implementations.setdefault(key, []).append(path)
    buckets: dict[str, list[str]] = {}
    for path, (key, role) in sorted(components.items()):
        status = statuses[path]
        candidates = implementations.get(key, [])
        blocked = status in {"DD", "AU", "UD", "UA", "DU", "AA", "UU", "??"} or "D" in status
        anchor = (
            candidates[0]
            if role in {"test", "docs"} and len(candidates) == 1 and not blocked
            and "D" not in statuses[candidates[0]] and statuses[candidates[0]] not in {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}
            else path
        )
        buckets.setdefault(anchor, []).append(path)

    clusters = []
    for index, (anchor, files) in enumerate(sorted(buckets.items()), 1):
        details = []
        risks = {"dependencies_not_verified", "ownership_unknown", "review_not_verified"}
        for path in files:
            xy = statuses[path]
            if xy == "??":
                risks.add("untracked_content_not_analyzed")
            if xy in {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}:
                risks.add("unmerged")
            if xy not in {"??", "!!"} and xy[0] != " " and xy[1] != " ":
                risks.add("mixed_staged_unstaged")
            if "D" in xy:
                risks.add("deletion_or_rename_requires_review")
            s, u = staged.get(path), unstaged.get(path)
            if s == (None, None) or u == (None, None):
                risks.add("binary_change")
            details.append({
                "path": path, "status": xy,
                "staged_lines": list(s) if s is not None else None,
                "unstaged_lines": list(u) if u is not None else None,
            })
        totals = {}
        for scope, inventory in (("staged", staged), ("unstaged", unstaged)):
            counts = [inventory[path] for path in files if path in inventory]
            totals[scope] = {
                "added": sum(a for a, _ in counts if a is not None),
                "deleted": sum(d for _, d in counts if d is not None),
                "non_text_files": sum(a is None or d is None for a, d in counts),
            }
        name = PurePosixPath(anchor).stem
        label = re.sub(r"[^a-zA-Z0-9_.-]+", "-", name)[:60] or "component"
        role = components[anchor][1]
        kind = {"docs": "docs", "test": "test"}.get(role, "chore")
        message = f"{kind}: update {label}"
        clusters.append({
            "cluster_id": index,
            "name": name,
            "category": role,
            "files": files,
            "summary": f"{len(files)} changed file(s) grouped by component name: {label}",
            "suggested_commit_message": message,
            "verification_status": "unknown",
            "risks": sorted(risks),
            "changes": details,
            "line_totals": totals,
        })
    return clusters


def _explicit_path_proposal(files: list[str]) -> dict[str, Any]:
    """Retain the legacy explicit-file classification for non-Git callers."""
    categories: dict[str, list[str]] = {}
    for path in sorted(set(files)):
        norm = path.lower().replace("\\", "/")
        if norm.startswith("docs/") or norm.endswith((".md", ".rst", ".txt")):
            category = "docs"
        elif norm.endswith((".toml", ".json", ".yaml", ".yml", ".ini", ".cfg", ".lock")) or "config" in norm:
            category = "config"
        elif "test" in norm:
            category = "tests"
        elif any(key in norm for key in ("model", "schema", "entity", "dto")):
            category = "models_or_schemas"
        elif any(key in norm for key in ("api", "service", "route", "controller", "endpoint")):
            category = "api_or_services"
        elif any(key in norm for key in ("core", "engine", "util", "helper", "lib")):
            category = "core"
        else:
            category = "other"
        categories.setdefault(category, []).append(path)
    clusters = [
        {
            "cluster_id": index,
            "name": category.replace("_", " ").title(),
            "category": category,
            "files": paths,
            "summary": f"{len(paths)} caller-supplied path(s); contents not inspected",
            "suggested_commit_message": f"chore: update {category.replace('_', ' ')}",
            "verification_status": "unknown",
            "risks": ["inventory_not_verified", "ownership_unknown", "dependencies_not_verified"],
        }
        for index, (category, paths) in enumerate(sorted(categories.items()), 1)
    ]
    return {
        "success": True, "total_files": sum(map(len, categories.values())),
        "cluster_count": len(clusters), "clusters": clusters,
        "summary": "Caller-supplied paths only; no Git inventory available",
        "method": "explicit_path_only", "verification_status": "unknown",
        "commit_ready": False, "limitations": ["No Git inventory, content, or verification inspected."],
    }


def run_split_changes(
    engine: Any,
    root: str,
    changed_files: list[str] | None,
    *,
    path_type: Any,
    subprocess_module: Any,
    hidden_run_kwargs_fn: Any,
) -> dict[str, Any]:
    resolved_root = path_type(engine._root(root))

    def git(*args: str) -> bytes:
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env["GIT_OPTIONAL_LOCKS"] = "0"
        cp = subprocess_module.run(
            ["git", "--no-pager", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", *args],
            cwd=str(resolved_root),
            capture_output=True,
            check=False,
            timeout=engine.git_status_timeout,
            env=env,
            **hidden_run_kwargs_fn(),
        )
        if cp.returncode != 0:
            raise ValueError("Git inventory unavailable")
        return cp.stdout

    # The historical explicit-list API also supports synthetic paths outside Git.
    # Never use that fallback after a worktree has been detected.
    try:
        top_raw = git("rev-parse", "--show-toplevel")
    except ValueError:
        if (
            isinstance(changed_files, list) and changed_files
            and all(isinstance(p, str) and p and not any(ord(c) < 32 for c in p) for p in changed_files)
            and not (resolved_root / ".git").exists()
        ):
            return {"root": str(resolved_root), **_explicit_path_proposal(changed_files)}
        return {"success": False, "error": "Git inventory unavailable", "retryable": True}
    except (OSError, subprocess_module.SubprocessError):
        return {"success": False, "error": "Git inventory unavailable", "retryable": True}

    try:
        top = path_type(os.fsdecode(top_raw.rstrip(b"\r\n"))).resolve()
        if top != resolved_root.resolve():
            raise ValueError("Expected the Git worktree root")
        args = ("status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames", "--ignore-submodules=none")
        before = git(*args)
        statuses = _parse_status(before)
        diff_args = ("diff", "--numstat", "-z", "--no-renames", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none")
        staged = _parse_numstat(git(*diff_args, "--cached", "--"))
        unstaged = _parse_numstat(git(*diff_args, "--"))
        if changed_files is not None:
            if not isinstance(changed_files, list) or any(not isinstance(p, str) or p not in statuses for p in changed_files):
                raise ValueError("Requested path is not in the current dirty worktree")
            statuses = {p: statuses[p] for p in dict.fromkeys(changed_files)}
        observed = inspect_change_atoms(
            str(top), statuses, staged, unstaged, git,
            persistent_cache=getattr(engine, "_change_summary_cache", None),
        )
        if git(*args) != before:
            raise ValueError("Worktree inventory changed during inspection")
        clusters = _group(statuses, staged, unstaged)
        by_path = observed["observations"]
        for cluster in clusters:
            atom_ids = []
            hunk_count = 0
            for change in cluster["changes"]:
                path = change["path"]
                atoms = by_path.get(path, [])
                change["atoms"] = atoms
                atom_ids.extend(atom["atom_id"] for atom in atoms)
                hunk_count += sum(atom["hunk_count"] for atom in atoms)
            cluster["group_key"] = identity("group-v1", str(top), *cluster["files"])
            cluster["observed_atom_ids"] = sorted(atom_ids)
            cluster["observed_hunk_count"] = hunk_count
            semantic_counts: dict[str, int] = {}
            semantic_observed = 0
            for change in cluster["changes"]:
                for atom in change["atoms"]:
                    semantic = atom["semantic"]
                    if semantic["status"] != "observed":
                        continue
                    semantic_observed += 1
                    for kind, count in semantic["change_counts"].items():
                        semantic_counts[kind] = semantic_counts.get(kind, 0) + count
            cluster["semantic_change_counts"] = semantic_counts
            cluster["semantic_observed_scopes"] = semantic_observed
            totals = cluster["line_totals"]
            added = sum(scope["added"] for scope in totals.values())
            deleted = sum(scope["deleted"] for scope in totals.values())
            cluster["summary"] += (
                f"; {hunk_count} observed text hunk(s), "
                f"+{added}/-{deleted} tracked lines across staged and unstaged scopes"
            )
            if semantic_counts:
                cluster["summary"] += "; AST: " + ", ".join(
                    f"{count} {kind}" for kind, count in sorted(semantic_counts.items())
                )
            if semantic_observed:
                symbols = [
                    symbol for change in cluster["changes"] for atom in change["atoms"]
                    if atom["semantic"]["status"] == "observed"
                    for symbol in atom["semantic"]["symbols"]
                ]
                names = sorted({
                    re.sub(r"[^a-zA-Z0-9_.-]", "", symbol["symbol"])
                    for symbol in symbols if symbol["symbol"] != "<module>"
                } - {""})
                if names:
                    first = names[0][:40]
                    suffix = " and related symbols" if len(names) > 1 else ""
                    kind = {"test": "test", "docs": "docs"}.get(cluster["category"], "chore")
                    cluster["suggested_commit_message"] = f"{kind}: update {first}{suffix}"
            if any(item["path"] in cluster["files"] for item in observed["unavailable"]):
                cluster["risks"] = sorted(set(cluster["risks"]) | {"patch_coverage_incomplete"})
    except (OSError, ValueError, subprocess_module.SubprocessError):
        return {
            "success": False,
            "error": "Cannot obtain a consistent Git change inventory; check root, requested paths and Git state.",
            "retryable": True,
        }

    return {
        "success": True,
        "root": str(resolved_root),
        "total_files": len(statuses),
        "cluster_count": len(clusters),
        "clusters": clusters,
        "summary": f"{len(statuses)} dirty file(s), {len(clusters)} proposed component group(s)",
        "method": "component_name_heuristic_v2",
        "patch_coverage_complete": not observed["unavailable"],
        "unavailable_patch_scopes": observed["unavailable"],
        "summary_cache_hits": observed["cache_hits"],
        "persistent_summary_cache_hits": observed["persistent_cache_hits"],
        "observed_change_set_id": identity(
            "observed-change-set-v1", str(top),
            *(atom["atom_id"] for path in sorted(observed["observations"])
              for atom in observed["observations"][path]),
        ),
        "verification_status": "unknown",
        "commit_ready": False,
        "limitations": [
            "Read-only observed patch identities; not a complete worktree fingerprint or authorization to stage or commit.",
            "File-level grouping only; dependencies and renames are not resolved.",
            "Git patch identities and line counts do not establish semantic intent or verification freshness.",
        ],
    }
