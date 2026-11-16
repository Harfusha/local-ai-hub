from __future__ import annotations

import ast
import os
import time
from pathlib import Path
from typing import Any, Callable

from .repo_tools import is_root_archive_path
from .search_pagination import pagination_bounds_error

_RELATION_SCAN_MAX_SECONDS = 3.0


def find_python_relations(
    self, root: str, symbol: str, limit: int, offset: int, direction: str,
    is_symlink_or_reparse_point: Callable[[Path], bool],
) -> dict[str, Any]:
    _is_symlink_or_reparse_point = is_symlink_or_reparse_point
    bounds_error = pagination_bounds_error(limit, offset)
    if bounds_error:
        return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": bounds_error}
    p_root = Path(self._root(root)).resolve()
    if not p_root.is_dir():
        return {"success": False, "error": f"root not found: {root}", "terminal": True, "retryable": False}
    if not isinstance(symbol, str) or not symbol.strip():
        return {"success": False, "status_code": 400, "error": "symbol must be a non-empty string", "terminal": True, "retryable": False}

    sym = symbol.strip()
    if (direction == "callers" and "." in sym and "::" not in sym) or (
        direction == "callees" and "." in sym and ("::" not in sym or "." in sym.split("::", 1)[1])
    ):
        return {
            "success": False, "status_code": 400, "terminal": True, "retryable": False,
            "error": "deterministic Python relation fallback requires an unqualified symbol or canonical :: qualification",
            "coverage": {"complete": False, "scope": "python_ast", "resolution": "unsupported_qualification"},
        }
    result_key = "callers" if direction == "callers" else "callees"
    page: list[dict[str, Any]] = []
    relation_count = 0
    skipped_files = 0
    scanned_files = 0
    scanned_bytes = 0
    incomplete = False
    scan_stopped = False
    incomplete_reasons: set[str] = set()
    deadline = time.monotonic() + _RELATION_SCAN_MAX_SECONDS
    max_files = max(1, int(getattr(self.repo_tools, "python_fallback_max_files", 8000)))
    max_file_bytes = max(1, int(getattr(self.repo_tools, "max_file_bytes", 2_000_000)))
    max_total_bytes = min(64_000_000, max_file_bytes * min(max_files, 32))
    max_directories = min(10_000, max_files * 4)
    excluded = {str(value).lower() for value in getattr(self.repo_tools, "ignore_dirs", set())}
    excluded.update({".git", ".venv", "venv", "node_modules", "vendor", "build", "dist"})
    directories_seen = 0
    source_files_seen = 0
    unsupported_languages: set[str] = set()
    matching_definitions: list[str] = []
    qualified_caller_symbol = direction == "callers" and "::" in sym
    caller_symbol_name = sym.rsplit("::", 1)[-1] if qualified_caller_symbol else sym
    callee_identity = sym.replace(".", "::") if direction == "callees" and "::" in sym else sym
    if qualified_caller_symbol:
        incomplete = True
        incomplete_reasons.add("qualified_symbol_scope_not_resolved")

    def walk_error(_error: OSError) -> None:
        nonlocal incomplete
        incomplete = True
        incomplete_reasons.add("directory_walk_error")

    def call_name(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    for directory, dirnames, filenames in os.walk(p_root, topdown=True, onerror=walk_error, followlinks=False):
        if time.monotonic() >= deadline:
            incomplete = True
            scan_stopped = True
            incomplete_reasons.add("time_budget_exhausted")
            break
        directories_seen += 1
        if directories_seen > max_directories:
            incomplete = True
            scan_stopped = True
            incomplete_reasons.add("directory_budget_exhausted")
            break
        kept_dirs = []
        for name in sorted(dirnames):
            if name.lower() in excluded or name.startswith("."):
                continue
            directory_path = Path(directory) / name
            try:
                if _is_symlink_or_reparse_point(directory_path):
                    incomplete = True
                    incomplete_reasons.add("reparse_point_skipped")
                    continue
                directory_path.resolve().relative_to(p_root)
                kept_dirs.append(name)
            except (OSError, ValueError):
                incomplete = True
                incomplete_reasons.add("directory_path_unverified")
        dirnames[:] = kept_dirs
        filenames.sort()
        for filename in filenames:
            if time.monotonic() >= deadline:
                incomplete = True
                scan_stopped = True
                incomplete_reasons.add("time_budget_exhausted")
                break
            path = Path(directory) / filename
            extension = path.suffix.lower()
            if extension == ".py":
                pass
            elif extension in {".cs", ".go", ".java", ".js", ".jsx", ".ts", ".tsx", ".rs", ".php", ".rb", ".cpp", ".c", ".h", ".hpp", ".kt", ".swift"}:
                unsupported_languages.add(extension.lstrip("."))
                continue
            else:
                continue
            relative = path.relative_to(p_root).as_posix()
            if is_root_archive_path(relative):
                continue
            source_files_seen += 1
            if source_files_seen > max_files:
                incomplete = True
                scan_stopped = True
                incomplete_reasons.add("file_budget_exhausted")
                break
            try:
                if _is_symlink_or_reparse_point(path):
                    skipped_files += 1
                    incomplete = True
                    incomplete_reasons.add("reparse_point_skipped")
                    continue
                resolved_path = path.resolve(strict=True)
                resolved_path.relative_to(p_root)
                _digest, lines = self.repo_tools._read_snapshot(path, max_bytes=max_file_bytes)
                content = "\n".join(lines)
                current_bytes = len(content.encode("utf-8", errors="replace"))
                if scanned_bytes + current_bytes > max_total_bytes:
                    incomplete = True
                    scan_stopped = True
                    incomplete_reasons.add("byte_budget_exhausted")
                    break
                scanned_bytes += current_bytes
                scanned_files += 1
                tree = ast.parse(content, filename=str(path))
            except (OSError, SyntaxError, UnicodeError, RecursionError, ValueError):
                skipped_files += 1
                incomplete = True
                incomplete_reasons.add("file_read_or_parse_error")
                continue

            module_name = relative[:-3].replace("/", ".")
            if module_name.endswith(".__init__"):
                module_name = module_name[:-9]
            module_identity = module_name.replace(".", "::")

            class _RelationVisitor(ast.NodeVisitor):
                def __init__(self):
                    self.scope_stack: list[str] = []

                def _visit_scope(self, node):
                    if time.monotonic() >= deadline:
                        nonlocal_incomplete[0] = True
                        return
                    self.scope_stack.append(node.name)
                    target_definition_name = sym.rsplit("::", 1)[-1]
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == target_definition_name:
                        matching_definitions.append("::".join([part for part in (module_identity, *self.scope_stack) if part]))
                    self.generic_visit(node)
                    self.scope_stack.pop()

                visit_FunctionDef = _visit_scope
                visit_AsyncFunctionDef = _visit_scope
                visit_ClassDef = _visit_scope

                def generic_visit(self, node):
                    if time.monotonic() >= deadline:
                        nonlocal_incomplete[0] = True
                        return
                    super().generic_visit(node)

                def visit_Call(self, node):
                    nonlocal relation_count
                    if time.monotonic() >= deadline:
                        nonlocal_incomplete[0] = True
                        return
                    target = call_name(node.func)
                    scope = ".".join(self.scope_stack) if self.scope_stack else "<module>"
                    if direction == "callers":
                        matched = target == caller_symbol_name
                    else:
                        qualified_scope = "::".join([part for part in (module_identity, *self.scope_stack) if part])
                        if "::" in sym or "." in sym:
                            scope_matches = (qualified_scope == callee_identity
                                             or qualified_scope.endswith("::" + callee_identity))
                        else:
                            scope_matches = bool(self.scope_stack and self.scope_stack[-1] == sym)
                        matched = bool(scope_matches and target)
                        if scope_matches and target is None:
                            nonlocal_incomplete[0] = True
                    if matched:
                        line_index = max(0, node.lineno - 1)
                        snippet = lines[line_index].strip() if line_index < len(lines) else ""
                        if direction == "callers":
                            item = {
                                "file": relative, "line": node.lineno, "col": node.col_offset,
                                "caller": scope, "callee": sym, "kind": "calls",
                                "match_scope": "syntactic_name", "snippet": snippet[:160],
                            }
                        else:
                            item = {
                                "file": relative, "line": node.lineno, "col": node.col_offset,
                                "caller": scope, "callee": target, "kind": "calls",
                                "match_scope": "syntactic_name", "snippet": snippet[:160],
                            }
                        if offset <= relation_count < offset + limit:
                            page.append(item)
                        relation_count += 1
                    self.generic_visit(node)

            nonlocal_incomplete = [False]
            visitor = _RelationVisitor()
            visitor.visit(tree)
            if nonlocal_incomplete[0]:
                incomplete = True
                scan_stopped = True
                incomplete_reasons.add("time_budget_exhausted")
        if scan_stopped:
            break

    if unsupported_languages:
        incomplete = True
        incomplete_reasons.add("unsupported_languages_present")
    if direction == "callees":
        if "::" in sym:
            matching = [definition for definition in matching_definitions
                        if definition == callee_identity or definition.endswith("::" + callee_identity)]
        else:
            matching = [definition for definition in matching_definitions if definition.endswith("::" + sym)]
        if len(matching) > 1:
            return {
                "success": False, "status_code": 422, "terminal": True, "retryable": False,
                "error": ("qualified function symbol resolves to multiple definitions"
                          if "::" in sym else "deterministic callee fallback requires a uniquely qualified function symbol"),
                "symbol": sym, "callees": [], "count": 0, "offset": offset, "limit": limit,
                "coverage": {"complete": False, "scan_complete": not incomplete, "scope": "python_ast",
                             "resolution": "ambiguous_qualified_definition" if "::" in sym else "ambiguous_unqualified_definition"},
            }
        elif not matching:
            if incomplete:
                return {
                    "success": False, "status_code": 503, "terminal": True, "retryable": False,
                    "error": "bounded deterministic scan could not resolve the requested Python function completely",
                    "symbol": sym, "callees": [], "count": 0, "offset": offset, "limit": limit,
                    "coverage": {
                        "complete": False, "scan_complete": False, "scope": "python_ast",
                        "resolution": "incomplete_scan", "incomplete_reasons": sorted(incomplete_reasons),
                    },
                }
            return {
                "success": False, "status_code": 422, "terminal": True, "retryable": False,
                "error": "deterministic callee fallback could not resolve the requested Python function",
                "symbol": sym, "callees": [], "count": 0, "offset": offset, "limit": limit,
                "coverage": {"complete": False, "scan_complete": not incomplete, "scope": "python_ast", "resolution": "definition_not_found"},
            }

    count_key = "caller_count" if direction == "callers" else "callee_count"
    result: dict[str, Any] = {
        "success": True,
        "symbol": sym,
        result_key: page,
        count_key: len(page),
        "count": len(page),
        "returned_count": len(page),
        "offset": offset,
        "limit": limit,
        "truncated": incomplete,
        "coverage": {
            "complete": not incomplete and offset == 0 and len(page) == relation_count,
            "scan_complete": not incomplete,
            "scope": "python_ast",
            "resolution": "syntactic_name",
            "returned": len(page),
            "limit": limit,
            "offset": offset,
            "scanned_files": scanned_files,
            "skipped_files": skipped_files,
            "scanned_bytes": scanned_bytes,
            "incomplete_reasons": sorted(incomplete_reasons),
            "unsupported_languages": sorted(unsupported_languages),
        },
        "freshness": {"status": "not_checked"},
    }
    if not incomplete:
        result["total_matches"] = relation_count
        has_more = offset + len(page) < relation_count
        result["has_more"] = has_more
        result["truncated"] = has_more
        if has_more:
            result["next_offset"] = offset + len(page)
    return result
