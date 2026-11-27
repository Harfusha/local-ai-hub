"""Read-only, conservative change grouping for the existing split_changes action."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import PurePosixPath
from typing import Any

from .change_index_tree import index_tree_oid
from .change_atoms import PatchBudgetExceeded, identity, inspect_change_atoms
from .change_dependencies import annotate_dependencies
from .process_utils import clean_git_env, run_hidden


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


def _parse_committed_status(raw: bytes) -> dict[str, str]:
    if raw and not raw.endswith(b"\0"):
        raise ValueError("Incomplete Git name-status")
    rows = raw.split(b"\0")[:-1]
    if len(rows) % 2:
        raise ValueError("Malformed Git name-status")
    records = []
    for index in range(0, len(rows), 2):
        flag, path = rows[index:index + 2]
        if flag not in {b"A", b"D", b"M", b"T"}:
            raise ValueError("Unsupported committed change type")
        records.append(flag + b"  " + path + b"\0")
    return _parse_status(b"".join(records))


def _resolve_commit(git: Any, revision: str) -> str:
    if (
        not isinstance(revision, str) or not revision or len(revision) > 512
        or revision.startswith("-") or any(ord(c) < 32 or c.isspace() for c in revision)
    ):
        raise ValueError("Invalid Git revision")
    resolved = git("rev-parse", "--verify", "--end-of-options", revision + "^{commit}").strip().decode("ascii")
    if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", resolved) is None:
        raise ValueError("Invalid resolved Git commit")
    return resolved


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
        if key and role == "implementation":
            implementations.setdefault(key, []).append(path)
    buckets: dict[str, list[str]] = {}
    for path, (key, role) in sorted(components.items()):
        status = statuses[path]
        candidates = implementations.get(key, [])
        blocked = status in {"DD", "AU", "UD", "UA", "DU", "AA", "UU"} or "D" in status
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
                risks.add("untracked_requires_review")
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


def _git_snapshot_metadata(git: Any) -> dict[str, str]:
    try:
        head = _resolve_commit(git, "HEAD")
    except ValueError:
        # Unborn and inaccessible HEAD must not be claimed as a verified revision.
        head = "unavailable"
    index = git("ls-files", "--stage", "-z")
    return {"head": head, "index_digest": hashlib.sha256(index).hexdigest(),
            "index_tree_oid": index_tree_oid(index, head) or ""}


def run_split_changes(
    engine: Any,
    root: str,
    changed_files: list[str] | None,
    *,
    path_type: Any,
    subprocess_module: Any,
    hidden_run_kwargs_fn: Any,
    base: str | None = None,
    head: str = "HEAD",
    git_runner: Any = run_hidden,
) -> dict[str, Any]:
    resolved_root = path_type(engine._root(root))

    def git(*args: str) -> bytes:
        env = clean_git_env(extra_env={
            "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1", "LC_ALL": "C",
        })
        patch = "--patch" in args
        cp = git_runner(
            ["git", "--no-pager", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", *args],
            cwd=str(resolved_root), capture_output=True, check=False,
            timeout=engine.git_status_timeout, env=env,
            stdin=subprocess_module.DEVNULL,
            max_output_bytes=512 * 1024 if patch else 4 * 1024 * 1024,
            **hidden_run_kwargs_fn(),
        )
        if getattr(cp, "stdout_truncated", False):
            if patch:
                raise PatchBudgetExceeded("Git patch output exceeds budget")
            raise ValueError("Git inventory exceeds output budget")
        if cp.returncode != 0:
            raise ValueError("Git inventory unavailable")
        return cp.stdout

    # The historical explicit-list API also supports synthetic paths outside Git.
    # Never use that fallback after a worktree has been detected.
    try:
        top_raw = git("rev-parse", "--show-toplevel")
    except ValueError:
        if (
            base is None and isinstance(changed_files, list) and changed_files
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
        diff_args = ("diff", "--numstat", "-z", "--no-renames", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none")
        comparison = None
        atom_git = git
        snapshot_before = None
        if base is None:
            snapshot_before = _git_snapshot_metadata(git)
            before = git(*args)
            statuses = _parse_status(before)
            staged = _parse_numstat(git(*diff_args, "--cached", "--"))
            unstaged = _parse_numstat(git(*diff_args, "--"))
        else:
            base_sha, head_sha = _resolve_commit(git, base), _resolve_commit(git, head)
            comparison = {"base": base_sha, "head": head_sha, "kind": "exact_tree_comparison"}
            statuses = _parse_committed_status(git(
                "diff", "--name-status", "-z", "--no-renames", "--no-ext-diff",
                "--no-textconv", "--ignore-submodules=none", base_sha, head_sha, "--",
            ))
            staged = _parse_numstat(git(*diff_args, base_sha, head_sha, "--"))
            unstaged = {}
            before = b""

            def committed_git(*patch_args: str) -> bytes:
                if patch_args[0] == "diff" and "--cached" in patch_args:
                    args_without_cached = tuple(arg for arg in patch_args if arg != "--cached")
                    boundary = args_without_cached.index("--")
                    return git(*args_without_cached[:boundary], base_sha, head_sha, *args_without_cached[boundary:])
                return git(*patch_args)
            atom_git = committed_git
        full_status_count = len(statuses)
        if changed_files is not None:
            if not isinstance(changed_files, list) or any(not isinstance(p, str) or p not in statuses for p in changed_files):
                raise ValueError("Requested path is not in the current dirty worktree")
            statuses = {p: statuses[p] for p in dict.fromkeys(changed_files)}
        observed = inspect_change_atoms(
            str(top), statuses, staged, unstaged, atom_git,
            staged_scope="committed" if comparison else "staged",
            persistent_cache=getattr(engine, "_change_summary_cache", None),
            fact_extractor=getattr(engine, "_extract_source_facts", None),
        )
        if comparison is None and (
            git(*args) != before or _git_snapshot_metadata(git) != snapshot_before
        ):
            raise ValueError("Git HEAD, index or inventory changed during inspection")
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
            cluster["group_key"] = identity("group-v1", str(top), "committed" if comparison else "worktree", *cluster["files"])
            if comparison:
                for change in cluster["changes"]:
                    change["status"] = change["status"][0]
                    change["committed_lines"] = change.pop("staged_lines")
                    change.pop("unstaged_lines")
                cluster["line_totals"] = {"committed": cluster["line_totals"]["staged"]}
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
                f"+{added}/-{deleted} tracked lines across observed scopes"
            )
            if semantic_counts:
                cluster["summary"] += "; structural/fact changes: " + ", ".join(
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
        dependency_plan = annotate_dependencies(clusters)
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
        "comparison": comparison,
        "dependency_plan": dependency_plan,
        "inventory_file_count": full_status_count,
        "inventory_scope": "selected_paths" if changed_files is not None else "git_visible_changes",
        "git_snapshot_metadata": snapshot_before,
        "cluster_count": len(clusters),
        "clusters": clusters,
        "summary": f"{len(statuses)} changed file(s), {len(clusters)} proposed component group(s)",
        "method": "component_name_heuristic_v2",
        "patch_coverage_complete": not observed["unavailable"],
        "git_visible_observation_complete": (
            not observed["unavailable"] and changed_files is None
            and (comparison is not None or snapshot_before["head"] != "unavailable")
        ),
        "unavailable_patch_scopes": observed["unavailable"],
        "summary_cache_hits": observed["cache_hits"],
        "persistent_summary_cache_hits": observed["persistent_cache_hits"],
        "observed_change_set_id": identity(
            "observed-change-set-v2", str(top),
            comparison["base"] if comparison else snapshot_before["head"],
            comparison["head"] if comparison else snapshot_before["index_digest"],
            *(identity(path, flag) for path, flag in sorted(statuses.items())),
            *(atom["atom_id"] for path in sorted(observed["observations"])
              for atom in observed["observations"][path]),
        ),
        "verification_status": "unknown",
        "commit_ready": False,
        "limitations": [
            "Read-only observed patch identities; not a complete worktree fingerprint or authorization to stage or commit.",
            "File-level groups with candidate import ordering and hunk symbol overlaps; dependencies and renames are not fully verified.",
            "Git patch identities and line counts do not establish semantic intent or verification freshness.",
        ],
    }
