from __future__ import annotations

from pathlib import Path, Path as _Path
from typing import Any
import ast as _ast
import os as _os


def run_code_invariants(
    engine: Any,
    root: str,
    path: str | None = None,
    *,
    path_type: Any = _Path,
    ast_module: Any = _ast,
    os_module: Any = _os,
    is_root_archive_path_fn: Any,
) -> dict[str, Any]:
    resolved_root = path_type(engine._root(root))
    target_paths: list[Path] = []
    unsupported_files: list[dict[str, str]] = []
    parse_errors: list[dict[str, Any]] = []
    scan_errors: list[dict[str, Any]] = []
    read_errors: list[dict[str, Any]] = []
    if not resolved_root.is_dir():
        return {
            "success": False,
            "complete": False,
            "error": "root_not_directory",
            "root": str(resolved_root),
            "files_checked": 0,
            "supported_languages": ["python"],
            "parse_errors": [],
            "scan_errors": [],
            "read_errors": [],
            "unsupported_files": [],
            "truncated": False,
            "violation_count": 0,
            "violations": [],
        }
    if path:
        candidate = (resolved_root / path).resolve(strict=False)
        if candidate.is_file():
            if not candidate.is_relative_to(resolved_root):
                return {
                    "success": False,
                    "complete": False,
                    "error": "path_outside_root",
                    "root": str(resolved_root),
                    "files_checked": 0,
                    "supported_languages": ["python"],
                    "parse_errors": [],
                    "scan_errors": [],
                    "read_errors": [],
                    "unsupported_files": [],
                    "truncated": False,
                    "violation_count": 0,
                    "violations": [],
                }
            if candidate.suffix.lower() == ".py":
                target_paths.append(candidate)
            else:
                unsupported_files.append({
                    "path": str(candidate.relative_to(resolved_root)).replace("\\", "/"),
                    "language": candidate.suffix.lower().lstrip(".") or "unknown",
                    "reason": "unsupported_language",
                })
        else:
            return {
                "success": False,
                "complete": False,
                "error": f"path not found: {path}",
                "root": str(resolved_root),
                "files_checked": 0,
                "supported_languages": ["python"],
                "parse_errors": [],
                "scan_errors": [],
                "read_errors": [],
                "unsupported_files": [],
                "truncated": False,
                "violation_count": 0,
                "violations": [],
            }
    else:
        truncated = False
        def record_scan_error(exc: OSError) -> None:
            scan_errors.append({
                "path": str(exc.filename or resolved_root),
                "reason": type(exc).__name__,
                "message": exc.strerror or str(exc),
            })

        ignored = {
            ".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", "tests", "tool-envs",
            *getattr(engine.repo_tools, "ignore_dirs", set()),
        }
        for dirpath, dirnames, filenames in os_module.walk(resolved_root, onerror=record_scan_error):
            # Repository-wide audits should cover shipped runtime code, not
            # test setup commands or managed dependency environments. An
            # explicit path remains available for fixture-level checks.
            rel_dir = os_module.path.relpath(dirpath, resolved_root).replace("\\", "/")
            if rel_dir != "." and (is_root_archive_path_fn(rel_dir) or any(part.startswith(".") for part in rel_dir.split("/"))):
                dirnames[:] = []
                continue
            dirnames[:] = [
                d for d in dirnames
                if d not in ignored
                and not d.startswith(".")
                and not is_root_archive_path_fn(d if rel_dir == "." else f"{rel_dir}/{d}")
            ]
            for f in filenames:
                rel_file = f if rel_dir == "." else f"{rel_dir}/{f}"
                if is_root_archive_path_fn(rel_file) or any(part.startswith(".") for part in rel_file.split("/")[:-1]):
                    continue
                if f.endswith(".py"):
                    if len(target_paths) >= 150:
                        truncated = True
                        break
                    target_paths.append(path_type(dirpath) / f)
            if truncated:
                break

    if path:
        truncated = False

    violations: list[dict[str, Any]] = []

    class InvariantVisitor(ast_module.NodeVisitor):
        def __init__(self, rel_path: str):
            self.rel_path = rel_path
            self.with_items: set[int] = set()

        def visit_With(self, node: ast_module.With) -> None:
            for item in node.items:
                if isinstance(item.context_expr, ast_module.Call):
                    self.with_items.add(id(item.context_expr))
            self.generic_visit(node)

        def visit_Call(self, node: ast_module.Call) -> None:
            func_name = ""
            if isinstance(node.func, ast_module.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast_module.Attribute):
                func_name = node.func.attr
                if isinstance(node.func.value, ast_module.Name):
                    full_name = f"{node.func.value.id}.{func_name}"
                    if full_name in ("subprocess.run", "requests.get", "requests.post", "requests.put", "requests.delete", "urllib.request.urlopen"):
                        has_timeout = any(kw.arg == "timeout" for kw in node.keywords)
                        if not has_timeout:
                            violations.append({
                                "path": self.rel_path,
                                "line": node.lineno,
                                "col": node.col_offset,
                                "rule": "missing_timeout",
                                "message": f"Call to '{full_name}' lacks explicit 'timeout' parameter",
                                "severity": "high",
                            })

            # ``os_module.open`` is a descriptor-level API, not a file object that
            # needs a context manager.  ``subprocess.Popen`` likewise has
            # no timeout argument; callers must bound communicate/wait.
            if isinstance(node.func, ast_module.Name) and func_name == "open" and id(node) not in self.with_items:
                violations.append({
                    "path": self.rel_path,
                    "line": node.lineno,
                    "col": node.col_offset,
                    "rule": "missing_with_open",
                    "message": "File 'open(...)' used without 'with' statement context manager",
                    "severity": "medium",
                })

            self.generic_visit(node)

    for p in target_paths:
        rel = str(p.relative_to(resolved_root)).replace("\\", "/")
        try:
            code = p.read_text(encoding="utf-8", errors="replace")
            tree = ast_module.parse(code, filename=rel)
        except OSError as exc:
            read_errors.append({
                "path": rel,
                "reason": type(exc).__name__,
                "message": str(exc),
            })
            continue
        except SyntaxError as exc:
            parse_errors.append({
                "path": rel,
                "reason": "syntax_error",
                "line": exc.lineno,
                "column": exc.offset,
                "message": exc.msg,
            })
            continue
        visitor = InvariantVisitor(rel)
        visitor.visit(tree)

    complete = not parse_errors and not scan_errors and not read_errors and not unsupported_files and not truncated
    return {
        "success": complete,
        "complete": complete,
        "root": str(resolved_root),
        "files_checked": len(target_paths),
        "supported_languages": ["python"],
        "parse_errors": parse_errors,
        "scan_errors": scan_errors,
        "read_errors": read_errors,
        "unsupported_files": unsupported_files,
        "truncated": truncated,
        "violation_count": len(violations),
        "violations": violations[:100],
    }

