"""Candidate change-group dependency ordering and hunk-to-symbol associations."""
from __future__ import annotations

import posixpath
from pathlib import PurePosixPath
from typing import Any


def _overlaps(start: int, count: int, span: Any) -> bool:
    if not isinstance(span, list) or len(span) != 2:
        return False
    return count > 0 and start <= span[1] and start + count - 1 >= span[0]


def annotate_hunks(atom: dict[str, Any]) -> None:
    semantic = atom.get("semantic", {})
    symbols = semantic.get("symbols", []) if semantic.get("method") == "python_ast_v2" else []
    for hunk in atom.get("hunks", []):
        names = sorted({
            item["symbol"] for item in symbols
            if _overlaps(hunk["old_start"], hunk["old_count"], item.get("before_range"))
            or _overlaps(hunk["new_start"], hunk["new_count"], item.get("after_range"))
        })
        hunk["symbol_candidates"] = names[:8]
        hunk["symbol_candidates_omitted"] = max(0, len(names) - 8)
        hunk["association"] = "range_overlap" if names else "unknown"


def _python_module_paths(path: str, name: str, available: set[str]) -> set[str]:
    if name.startswith("."):
        level = len(name) - len(name.lstrip("."))
        parent = PurePosixPath(path).parent
        for _ in range(level - 1):
            if parent == PurePosixPath("."):
                return set()
            parent = parent.parent
        tail = name[level:].replace(".", "/")
        base = posixpath.normpath(posixpath.join(parent.as_posix(), tail))
        targets = {base + ".py", posixpath.join(base, "__init__.py")}
        return available & targets
    tail = name.replace(".", "/")
    matches = set()
    for candidate in available:
        if candidate in {tail + ".py", tail + "/__init__.py"} or candidate.endswith(("/" + tail + ".py", "/" + tail + "/__init__.py")):
            matches.add(candidate)
    return matches


def _js_module_paths(path: str, name: str, available: set[str]) -> set[str]:
    if not name.startswith("."):
        return set()
    base = posixpath.normpath(posixpath.join(posixpath.dirname(path), name))
    if base.startswith("../") or base == ".." or base.startswith("/"):
        return set()
    extensions = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".vue", ".svelte")
    targets = {base} | {base + ext for ext in extensions} | {base + "/index" + ext for ext in extensions}
    # TypeScript Node-style imports may name the emitted JS extension.
    for emitted, source_extensions in ((".js", (".ts", ".tsx")), (".mjs", (".mts",)), (".cjs", (".cts",))):
        if base.endswith(emitted):
            targets.update(base[:-len(emitted)] + ext for ext in source_extensions)
    return available & targets


def _dependency_units(edges: dict[str, set[str]]) -> list[list[str]]:
    """Order strongly connected groups as indivisible candidate units.

    Iterative Kosaraju avoids recursion limits on long dependency chains.
    Edges point from a consumer to its prerequisites.
    """
    visited: set[str] = set()
    finished: list[str] = []
    for root in sorted(edges):
        if root in visited:
            continue
        stack = [(root, False)]
        while stack:
            key, expanded = stack.pop()
            if expanded:
                finished.append(key)
                continue
            if key in visited:
                continue
            visited.add(key)
            stack.append((key, True))
            stack.extend((dep, False) for dep in sorted(edges[key], reverse=True) if dep not in visited)
    reverse: dict[str, set[str]] = {key: set() for key in edges}
    for key, deps in edges.items():
        for dep in deps:
            reverse[dep].add(key)
    components: list[list[str]] = []
    membership: dict[str, int] = {}
    for root in reversed(finished):
        if root in membership:
            continue
        component_id = len(components)
        members = []
        pending = [root]
        while pending:
            key = pending.pop()
            if key in membership:
                continue
            membership[key] = component_id
            members.append(key)
            pending.extend(reverse[key] - membership.keys())
        components.append(sorted(members))
    remaining = {i: set() for i in range(len(components))}
    for key, deps in edges.items():
        own = membership[key]
        remaining[own].update(membership[dep] for dep in deps if membership[dep] != own)
    units = []
    while remaining:
        ready = sorted((i for i, deps in remaining.items() if not deps), key=components.__getitem__)
        if not ready:
            raise ValueError("Invalid component graph")
        units.extend(components[i] for i in ready)
        for i in ready:
            del remaining[i]
        for deps in remaining.values():
            deps.difference_update(ready)
    return units


def annotate_dependencies(groups: list[dict[str, Any]]) -> dict[str, Any]:
    """Order candidate groups by uniquely matched import paths, never assert completeness."""
    owner = {path: group["group_key"] for group in groups for path in group["files"]}
    available = set(owner)
    declarations: dict[str, set[str]] = {}
    old_declarations: dict[str, set[str]] = {}
    for group in groups:
        for change in group["changes"]:
            for atom in change.get("atoms", []):
                for name in atom.get("semantic", {}).get("declarations_after", []):
                    declarations.setdefault(name.lower(), set()).add(change["path"])
                for name in atom.get("semantic", {}).get("declarations_before", []):
                    old_declarations.setdefault(name.lower(), set()).add(change["path"])
                annotate_hunks(atom)
    edges: dict[str, set[str]] = {group["group_key"]: set() for group in groups}
    evidence: dict[str, list[dict[str, str]]] = {key: [] for key in edges}
    ambiguous = 0
    unmatched = 0
    import_observations = 0
    unavailable_scopes = 0
    truncated_scopes = 0
    removed_declarations = 0
    removed_paths = {change["path"] for group in groups for change in group["changes"]
                     if change.get("status") in {"D", "D ", " D"}}
    removal_edges = 0
    unresolved_removed_imports = 0
    for group in groups:
        key = group["group_key"]
        for change in group["changes"]:
            path = change["path"]
            suffix = PurePosixPath(path).suffix.lower()
            for atom in change.get("atoms", []):
                semantic = atom.get("semantic", {})
                if semantic.get("status") != "observed":
                    unavailable_scopes += 1
                if semantic.get("imports_truncated") or semantic.get("imports_before_truncated") or semantic.get("declarations_truncated") or semantic.get("declarations_before_truncated"):
                    truncated_scopes += 1
                for name in semantic.get("imports_after", []):
                    import_observations += 1
                    if suffix == ".py":
                        matches = _python_module_paths(path, name, available)
                    elif suffix in {".php", ".ctp"}:
                        matches = declarations.get(name.lower(), set())
                        if not matches:
                            before_matches = old_declarations.get(name.lower(), set())
                            if len(before_matches) == 1:
                                old_path = next(iter(before_matches))
                                if old_path in removed_paths:
                                    matches = before_matches
                                else:
                                    # A renamed or removed declaration in a surviving file
                                    # is not a dependency proof. Surface it for review.
                                    removed_declarations += 1
                                    group["risks"] = sorted(set(group["risks"]) | {"import_candidate_points_to_removed_declaration"})
                    else:
                        matches = _js_module_paths(path, name, available)
                    if len(matches) != 1:
                        ambiguous += int(len(matches) > 1)
                        unmatched += int(not matches)
                        continue
                    target = next(iter(matches))
                    other = owner[target]
                    if other == key:
                        continue
                    if target in removed_paths:
                        unresolved_removed_imports += 1
                        group["risks"] = sorted(set(group["risks"]) | {"import_candidate_points_to_removed_path"})
                    edges[key].add(other)
                    if len(evidence[key]) < 16:
                        item = {"source": path, "target": target, "kind": "import_candidate"}
                        if item not in evidence[key]:
                            evidence[key].append(item)
                semantic = atom.get("semantic", {})
                # For a removed module, consumers must drop their imports
                # before the provider disappears. Only reverse the edge when
                # both sides of the import observation are available, and the
                # file has one observed scope (mixed stages are ambiguous).
                if (len(change.get("atoms", [])) != 1 or semantic.get("status") != "observed"
                        or semantic.get("imports_before_truncated") is not False
                        or semantic.get("imports_truncated") is not False):
                    continue
                removed_imports = set(semantic.get("imports_before", [])) - set(semantic.get("imports_after", []))
                for name in sorted(removed_imports):
                    if suffix in {".php", ".ctp"}:
                        matches = old_declarations.get(name.lower(), set())
                    elif suffix == ".py":
                        matches = _python_module_paths(path, name, available)
                    else:
                        matches = _js_module_paths(path, name, available)
                    if len(matches) != 1:
                        continue
                    target = next(iter(matches))
                    other = owner[target]
                    if target not in removed_paths or other == key:
                        continue
                    if key not in edges[other]:
                        removal_edges += 1
                    edges[other].add(key)
                    item = {"source": target, "target": path, "kind": "import_removal_candidate"}
                    if len(evidence[other]) < 16 and item not in evidence[other]:
                        evidence[other].append(item)
    remaining = {key: set(deps) for key, deps in edges.items()}
    order = []
    while remaining:
        ready = sorted(key for key, deps in remaining.items() if not deps)
        if not ready:
            break
        order.extend(ready)
        for key in ready:
            del remaining[key]
        for deps in remaining.values():
            deps.difference_update(ready)
    units = _dependency_units(edges)
    membership = {key: unit for unit in units for key in unit}
    for group in groups:
        key = group["group_key"]
        group["dependency_component_keys"] = membership[key]
        group["dependency_group_candidates"] = sorted(edges[key])
        group["dependency_evidence"] = evidence[key]
        if len(membership[key]) > 1:
            group["risks"] = sorted(set(group["risks"]) | {"dependency_cycle_requires_joint_commit"})
    return {
        "method": "observed_import_candidates_v1",
        "candidate_order": order,
        "blocked_group_keys": sorted(remaining),
        "candidate_commit_units": units,
        "cyclic_unit_count": sum(len(unit) > 1 for unit in units),
        "ambiguous_import_count": ambiguous,
        "unmatched_import_count": unmatched,
        "observed_import_count": import_observations,
        "unavailable_semantic_scopes": unavailable_scopes,
        "truncated_import_or_declaration_scopes": truncated_scopes,
        "removed_declaration_import_candidates": removed_declarations,
        "removed_import_ordering_edges": removal_edges,
        "unresolved_removed_import_count": unresolved_removed_imports,
        "dependencies_verified": False,
    }
