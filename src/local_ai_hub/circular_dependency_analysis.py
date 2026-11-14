from __future__ import annotations

from pathlib import Path
from typing import Any


def find_circular_dependencies(
    root: str,
    language: str,
    max_depth: int,
    max_cycles: int,
    code_index: Any,
) -> dict[str, Any]:
    """Detect circular module import cycles from an indexed import graph."""
    if type(max_depth) is not int or not 1 <= max_depth <= 256:
        raise ValueError("max_depth must be an integer between 1 and 256")
    if type(max_cycles) is not int or not 1 <= max_cycles <= 10000:
        raise ValueError("max_cycles must be an integer between 1 and 10000")
    p_root = Path(root).expanduser().resolve(strict=False)
    if not p_root.is_dir():
        return {"success": False, "error": f"directory not found: {root}"}

    skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"}
    mod_to_file: dict[str, Path] = {}
    file_to_mod: dict[Path, str] = {}

    if code_index is None:
        return {"success": False, "error": "Python import index unavailable", "index_state": "unindexed"}
    graph_reader = getattr(code_index, "python_module_import_graph", None)
    if not callable(graph_reader):
        return {"success": False, "error": "Python import index API unavailable", "index_state": "unindexed"}
    indexed_graph = graph_reader(str(p_root))
    if not indexed_graph.get("success"):
        return {
            "success": False,
            "error": indexed_graph.get("error", "Python import index unavailable"),
            "index_state": indexed_graph.get("state", "unindexed"),
        }
    py_files = sorted(
        p_root / Path(relative)
        for relative in indexed_graph.get("paths", [])
        if not any(part in skip_dirs for part in Path(relative).parts)
    )

    for p in py_files:
        rel = p.relative_to(p_root)
        parts = list(rel.parts)
        if parts[-1].endswith(".py"):
            parts[-1] = parts[-1][:-3]
        if parts and parts[-1] == "__init__":
            parts.pop()
        if not parts:
            continue
        mod_name = ".".join(parts)
        mod_to_file[mod_name] = p
        file_to_mod[p] = mod_name

    if not file_to_mod:
        return {"success": False, "error": "no indexed Python modules", "index_state": "unindexed"}

    def _find_matches(target: str) -> list[str]:
        matches: list[str] = []
        cur = target
        while cur:
            if cur in mod_to_file:
                matches.append(cur)
            if "." in cur:
                cur = cur.rsplit(".", 1)[0]
            else:
                break
        return matches

    graph: dict[str, set[str]] = {module: set() for module in mod_to_file}
    for edge in indexed_graph.get("imports", []):
        relative_path = Path(str(edge.get("path", "")))
        source_path = (p_root / relative_path).resolve(strict=False)
        mod_name = file_to_mod.get(source_path)
        if not mod_name:
            continue
        target = str(edge.get("target", ""))
        if not target:
            continue
        if target.startswith("."):
            level = len(target) - len(target.lstrip("."))
            package_parts = mod_name.split(".") if relative_path.name == "__init__.py" else mod_name.split(".")[:-1]
            if level - 1 > len(package_parts):
                continue
            base_parts = package_parts[:len(package_parts) - (level - 1)]
            remainder = target[level:]
            target = ".".join([*base_parts, remainder] if remainder else base_parts)
        for known in _find_matches(target):
            if known != mod_name:
                graph[mod_name].add(known)

    cycles: list[list[str]] = []
    seen_cycles: set[tuple[str, ...]] = set()
    visited: set[str] = set()
    stack: list[str] = []
    stack_set: set[str] = set()
    truncated = False
    cycle_limit_exceeded = False

    def dfs(curr: str):
        nonlocal truncated, cycle_limit_exceeded
        visited.add(curr)
        stack.append(curr)
        stack_set.add(curr)
        for nxt in sorted(graph.get(curr, [])):
            if cycle_limit_exceeded:
                break
            if nxt in stack_set:
                idx = stack.index(nxt)
                cycle = stack[idx:] + [nxt]
                min_idx = cycle[:-1].index(min(cycle[:-1]))
                canon = cycle[min_idx:-1] + cycle[:min_idx] + [cycle[min_idx]]
                canon_key = tuple(canon)
                if canon_key not in seen_cycles:
                    if len(cycles) >= max_cycles:
                        truncated = True
                        cycle_limit_exceeded = True
                        break
                    cycles.append(canon)
                    seen_cycles.add(canon_key)
            elif nxt not in visited:
                if len(stack) >= max_depth:
                    truncated = True
                else:
                    dfs(nxt)
        stack.pop()
        stack_set.remove(curr)

    for node in sorted(graph.keys()):
        if cycle_limit_exceeded:
            break
        if node not in visited:
            dfs(node)

    formatted_cycles = []
    for cycle in cycles:
        formatted_cycles.append({
            "cycle": cycle,
            "chain": " -> ".join(cycle),
            "length": len(cycle) - 1,
            "files": [str(mod_to_file.get(module, module)) for module in cycle[:-1]],
        })

    return {
        "success": True,
        "root": str(p_root),
        "modules_scanned": len(file_to_mod),
        "cycles_found": len(formatted_cycles),
        "cycles": formatted_cycles,
        "has_cycles": len(formatted_cycles) > 0,
        "truncated": truncated,
        "complete": not truncated,
    }
