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
    return available & ({base} | {base + ext for ext in extensions} | {base + "/index" + ext for ext in extensions})


def annotate_dependencies(groups: list[dict[str, Any]]) -> dict[str, Any]:
    """Order candidate groups by uniquely matched import paths, never assert completeness."""
    owner = {path: group["group_key"] for group in groups for path in group["files"]}
    available = set(owner)
    declarations: dict[str, set[str]] = {}
    for group in groups:
        for change in group["changes"]:
            for atom in change.get("atoms", []):
                for name in atom.get("semantic", {}).get("declarations_after", []):
                    declarations.setdefault(name.lower(), set()).add(change["path"])
                annotate_hunks(atom)
    edges: dict[str, set[str]] = {group["group_key"]: set() for group in groups}
    evidence: dict[str, list[dict[str, str]]] = {key: [] for key in edges}
    ambiguous = 0
    for group in groups:
        key = group["group_key"]
        for change in group["changes"]:
            path = change["path"]
            suffix = PurePosixPath(path).suffix.lower()
            for atom in change.get("atoms", []):
                for name in atom.get("semantic", {}).get("imports_after", []):
                    if suffix == ".py":
                        matches = _python_module_paths(path, name, available)
                    elif suffix in {".php", ".ctp"}:
                        matches = declarations.get(name.lower(), set())
                    else:
                        matches = _js_module_paths(path, name, available)
                    if len(matches) != 1:
                        ambiguous += int(len(matches) > 1)
                        continue
                    target = next(iter(matches))
                    other = owner[target]
                    if other == key:
                        continue
                    edges[key].add(other)
                    if len(evidence[key]) < 16:
                        item = {"source": path, "target": target, "kind": "import_candidate"}
                        if item not in evidence[key]:
                            evidence[key].append(item)
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
    for group in groups:
        key = group["group_key"]
        group["dependency_group_candidates"] = sorted(edges[key])
        group["dependency_evidence"] = evidence[key]
        if key in remaining:
            group["risks"] = sorted(set(group["risks"]) | {"dependency_cycle_or_blocked"})
    return {
        "method": "observed_import_candidates_v1",
        "candidate_order": order,
        "blocked_group_keys": sorted(remaining),
        "ambiguous_import_count": ambiguous,
        "dependencies_verified": False,
    }
