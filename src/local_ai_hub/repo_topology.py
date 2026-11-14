from __future__ import annotations

import ast
import os
import stat
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable


def repo_topology(
    root: str,
    *,
    root_resolver: Callable[[str], str],
    repo_tools: Any,
    is_symlink_or_reparse_point: Callable[[Path], bool],
    classify_layer: Callable[[str, str], str],
    build_summary: Callable[..., str],
) -> dict[str, Any]:
    """Return a bounded local Python import graph and heuristic path labels."""
    import sys

    resolved_root = Path(root_resolver(root)).resolve()
    root_str = str(resolved_root)
    file_limit = 20_000
    per_file_limit = 256 * 1024
    total_bytes_limit = 8 * 1024 * 1024
    edge_limit = 5_000
    sample_limit = 100
    deadline = time.monotonic() + 3.0
    complete = True
    errors: list[str] = []
    excluded_dirs = sorted(getattr(repo_tools, "ignore_dirs", set()))
    excluded = {
        ".git", ".hg", ".svn", ".venv", "venv", ".tox", "node_modules",
        "__pycache__", "docs", "doc", "plans", "tests", "test", "fixtures",
        "fixture", "examples", "example", "archive", "archives", "artifacts",
        "handoff", "cache", "caches", "build", "dist", "target", "vendor",
        "generated",
    }

    source_roots: list[Path] = []
    src_root = resolved_root / "src"
    if src_root.is_dir():
        resolved_src = src_root.resolve()
        if is_symlink_or_reparse_point(src_root) or not resolved_src.is_relative_to(resolved_root):
            complete = False
            errors.append("unsafe_path")
        else:
            source_roots.append(resolved_src)
    packages_root = resolved_root / "packages"
    if packages_root.is_dir():
        try:
            if is_symlink_or_reparse_point(packages_root):
                complete = False
                errors.append("unsafe_path")
            else:
                package_entries: list[Path] = []
                for package in packages_root.iterdir():
                    if len(package_entries) >= file_limit or time.monotonic() >= deadline:
                        complete = False
                        errors.append("source_root_limit_or_deadline")
                        break
                    package_entries.append(package)
                for package in sorted(package_entries):
                    if time.monotonic() >= deadline:
                        complete = False
                        errors.append("source_root_deadline")
                        break
                    package_src = package / "src"
                    if not package_src.is_dir():
                        continue
                    resolved_package_src = package_src.resolve()
                    if (
                        is_symlink_or_reparse_point(package)
                        or is_symlink_or_reparse_point(package_src)
                        or not resolved_package_src.is_relative_to(resolved_root)
                    ):
                        complete = False
                        errors.append("unsafe_path")
                        continue
                    source_roots.append(resolved_package_src)
        except OSError:
            complete = False
            errors.append("source_root_error")
    unsafe_source_root = "unsafe_path" in errors and not source_roots
    use_project_root = not source_roots and not unsafe_source_root
    inventory_roots = source_roots or ([resolved_root] if use_project_root else [])

    def eligible_rel(path: Path) -> str | None:
        try:
            rel = path.relative_to(resolved_root)
        except ValueError:
            return None
        if any(part.lower() in excluded for part in rel.parts[:-1]):
            return None
        if use_project_root or any(path.is_relative_to(base) for base in source_roots):
            return rel.as_posix()
        return None

    eligible: list[tuple[str, Path]] = []
    try:
        for inventory_root in inventory_roots:
            inventory_count = 0
            for candidate in repo_tools.iter_files(
                str(inventory_root), max_files=file_limit + 1
            ):
                if time.monotonic() >= deadline:
                    complete = False
                    errors.append("inventory_deadline")
                    break
                inventory_count += 1
                if inventory_count > file_limit:
                    complete = False
                    errors.append("inventory_limit")
                    break
                rel = eligible_rel(candidate)
                if rel is None or not rel.lower().endswith(".py"):
                    continue
                if len(eligible) >= file_limit:
                    complete = False
                    errors.append("file_limit")
                    break
                eligible.append((rel, candidate))
            if any(error in errors for error in ("inventory_deadline", "file_limit", "inventory_limit")):
                break
    except Exception:
        complete = False
        errors.append("inventory_error")

    layers: dict[str, list[str]] = {
        name: []
        for name in (
            "entrypoints", "presentation", "core_services",
            "domain_models", "infrastructure", "utilities",
        )
    }
    module_paths: dict[str, list[str]] = defaultdict(list)
    path_modules: dict[str, str] = {}
    for rel, path in eligible:
        base = next(
            (source_root for source_root in source_roots if path.is_relative_to(source_root)),
            resolved_root,
        )
        module_parts = list(path.relative_to(base).with_suffix("").parts)
        if module_parts[-1] == "__init__":
            module_parts.pop()
        module = ".".join(module_parts)
        if module:
            module_paths[module].append(rel)
            path_modules[rel] = module

        layer = classify_layer(rel, path.name)
        layers[layer].append(rel)

    local_top_levels = {module.partition(".")[0] for module in module_paths}

    def resolve_local(module: str) -> str | None:
        matches = module_paths.get(module, [])
        if len(matches) == 1:
            return matches[0]
        return "" if matches else None

    def has_unsafe_ancestor(path: Path) -> bool:
        current = resolved_root
        for part in path.relative_to(resolved_root).parts:
            current = current / part
            if is_symlink_or_reparse_point(current):
                return True
        return False

    edges: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    external: list[dict[str, Any]] = []
    stdlib_count = total_bytes = files_read = skipped = parse_errors = 0
    for file_index, (rel, path) in enumerate(eligible):
        if len(edges) + len(unresolved) + len(external) >= edge_limit:
            complete = False
            errors.append("edge_limit")
            skipped += len(eligible) - file_index
            break
        if time.monotonic() >= deadline or total_bytes >= total_bytes_limit:
            complete = False
            errors.append(
                "analysis_deadline"
                if time.monotonic() >= deadline
                else "aggregate_byte_limit"
            )
            skipped += len(eligible) - file_index
            break
        try:
            if has_unsafe_ancestor(path) or not path.resolve().is_relative_to(resolved_root):
                raise ValueError("unsafe_path")
            flags = (
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0)
                | getattr(os, "O_BINARY", 0)
            )
            fd = os.open(path, flags)
            try:
                before = os.fstat(fd)
                path_before = os.stat(path, follow_symlinks=False)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_size > per_file_limit
                    or (before.st_dev, before.st_ino) != (path_before.st_dev, path_before.st_ino)
                ):
                    raise ValueError("unsafe_path")
                remaining = min(per_file_limit, total_bytes_limit - total_bytes)
                with os.fdopen(fd, "rb", closefd=False) as handle:
                    raw = handle.read(remaining + 1)
                after = os.fstat(fd)
                path_after = os.stat(path, follow_symlinks=False)
                if (
                    len(raw) > remaining
                    or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    or (after.st_dev, after.st_ino) != (path_after.st_dev, path_after.st_ino)
                    or has_unsafe_ancestor(path)
                ):
                    raise ValueError("file_changed_or_byte_limit")
                total_bytes += len(raw)
                files_read += 1
                parsed = ast.parse(raw.decode("utf-8"), filename=rel)
            finally:
                os.close(fd)
        except (OSError, SyntaxError, UnicodeError, ValueError) as exc:
            complete = False
            skipped += 1
            parse_errors += 1
            errors.append(str(exc) if isinstance(exc, ValueError) else "read_or_parse_error")
            continue

        source_module = path_modules.get(rel)
        if not source_module:
            continue
        for node in ast.walk(parsed):
            if time.monotonic() >= deadline:
                complete = False
                errors.append("analysis_deadline")
                break
            imports: list[tuple[str, int, bool]] = []
            if isinstance(node, ast.Import):
                imports = [(alias.name, node.lineno, False) for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                package_parts = source_module.split(".")[:-1]
                if Path(rel).name == "__init__.py":
                    package_parts = source_module.split(".")
                if node.level > len(package_parts):
                    # An invalid relative level cannot become a root import.
                    imports = [("." * node.level + (node.module or ""), node.lineno, True)]
                else:
                    prefix = package_parts[: len(package_parts) - node.level + 1] if node.level else []
                    if node.module:
                        prefix.extend(node.module.split("."))
                    base_module = ".".join(prefix)
                    base_matches = module_paths.get(base_module, [])
                    modules = [base_module] if base_matches else []
                    base_is_package = not base_matches or all(
                        Path(match).name == "__init__.py" for match in base_matches
                    )
                    if base_is_package:
                        for alias in node.names:
                            child = f"{base_module}.{alias.name}"
                            if alias.name != "*" and child in module_paths:
                                modules.append(child)
                    if not modules:
                        modules = [base_module]
                    imports = [
                        (module, node.lineno, bool(node.level))
                        for module in dict.fromkeys(modules) if module
                    ]

            for imported, line, is_relative in imports:
                target = resolve_local(imported)
                if target == "":
                    unresolved.append({"source": rel, "module": imported, "line": line, "reason": "ambiguous_local_module"})
                elif target:
                    edges.append({"source": rel, "target": target, "module": imported, "line": line})
                elif is_relative:
                    unresolved.append({"source": rel, "module": imported, "line": line, "reason": "unresolved_relative_import"})
                elif imported.partition(".")[0] in local_top_levels:
                    unresolved.append({"source": rel, "module": imported, "line": line, "reason": "unresolved_local_module"})
                elif imported.split(".", 1)[0] in sys.stdlib_module_names:
                    stdlib_count += 1
                else:
                    external.append({"source": rel, "module": imported, "line": line})
                if len(edges) + len(unresolved) + len(external) >= edge_limit:
                    complete = False
                    errors.append("edge_limit")
                    break
            if len(edges) + len(unresolved) + len(external) >= edge_limit:
                break

    hubs = [
        {"path": path, "in_degree": count}
        for path, count in Counter(
            target for _source, target in dict.fromkeys(
                (edge["source"], edge["target"]) for edge in edges
            )
        ).most_common(10)
    ]
    has_api = bool(layers["presentation"])
    has_services = bool(layers["core_services"])
    has_cli = bool(layers["entrypoints"])
    if has_api and has_services:
        pattern = "Layered Service / Web Application"
    elif has_cli and has_services:
        pattern = "Modular CLI Application"
    elif has_services:
        pattern = "Library / Application Engine"
    else:
        pattern = "Package / Module Collection"
    graph_complete = complete and not unresolved and "edge_limit" not in errors
    graph = {
        "scope": "bounded Python AST imports resolved against unique local source modules",
        "nodes": len(path_modules), "edge_count": len(edges), "edges": edges[:sample_limit], "hub_paths": hubs,
        "unresolved_count": len(unresolved), "unresolved": unresolved[:sample_limit],
        "external_import_count": len(external), "external_imports": external[:sample_limit],
        "stdlib_import_count": stdlib_count, "complete": graph_complete,
        "truncated": any(len(items) > sample_limit for items in (edges, unresolved, external)),
    }
    return {
        "success": True, "root": root_str,
        "architecture_pattern_hypothesis": pattern,
        "architecture_pattern_verified": False,
        "heuristic_layers": layers, "module_graph": graph,
        "summary_markdown": build_summary(
            resolved_root.name, pattern, layers, graph_complete, edges
        ),
        "coverage": {
            "complete": complete,
            "inventory_scope": "eligible Python source under recognized roots; docs, plans, tests and fixtures excluded",
            "deadline_kind": "cooperative", "files_seen": len(eligible),
            "files_read": files_read, "files_skipped": skipped,
            "parse_errors": parse_errors, "bytes_read": total_bytes,
            "file_limit": file_limit, "per_file_bytes_limit": per_file_limit,
            "aggregate_bytes_limit": total_bytes_limit, "excluded_dirs": excluded_dirs,
            "errors": sorted(set(errors)), "module_graph_resolved": True,
            "module_graph_complete": graph_complete,
            "architecture_pattern_basis": "filename and path heuristics",
            "architecture_pattern_verified": False,
        },
        "import_scope": "Python AST imports resolved only against unique local modules in the bounded source inventory",
    }
