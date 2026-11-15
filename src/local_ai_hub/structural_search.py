from __future__ import annotations

import ast
import logging
import os
import re
import stat
from pathlib import Path
from typing import Any, Callable

from .process_utils import canonical_root


logger = logging.getLogger(__name__)


def search_structurally(
    root: str,
    pattern: str,
    path: str | None = None,
    max_results: int = 30,
    *,
    is_symlink_or_reparse_point: Callable[[Path], bool],
) -> dict[str, Any]:
    """Syntax-aware structural code search across Python and multi-language repositories."""
    canon_root = canonical_root(root)
    root_path = Path(canon_root)
    if not root_path.is_dir():
        return {"success": False, "error": f"invalid root directory: {root}"}

    target_pattern = (pattern or "").strip().lower()
    if not target_pattern:
        return {"success": False, "error": "pattern is required"}

    output_limit = max(0, int(max_results))
    result_probe_limit = output_limit + 1
    file_limit = 400
    results: list[dict[str, Any]] = []
    read_errors = 0
    parse_errors = 0
    ignore_dirs = {".git", "node_modules", "vendor", "__pycache__", ".venv", "venv", "dist", "build"}

    def authorized_path(candidate: Path) -> Path:
        relative = candidate.relative_to(root_path)
        if any(part in {"..", ""} for part in relative.parts):
            raise PermissionError("path must stay within repository root")
        current = root_path
        for part in relative.parts:
            current = current / part
            if is_symlink_or_reparse_point(current):
                raise PermissionError("path cannot traverse symlinks or reparse points")
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root_path)
        return resolved

    if path:
        candidate = Path(path.replace("\\", "/"))
        if not candidate.is_absolute():
            candidate = root_path / candidate
        try:
            candidate = authorized_path(candidate)
        except (ValueError, PermissionError):
            return {"success": False, "status_code": 403, "terminal": True, "retryable": False,
                    "error": "path must stay within repository root without symlinks or reparse points"}
        except OSError:
            return {"success": False, "status_code": 404, "terminal": True, "retryable": False,
                    "error": "source path unavailable"}
        else:
            files_to_scan = [candidate] if candidate.is_file() else []
    else:
        files_to_scan = []
        for cur_root, dirs, filenames in os.walk(root_path):
            safe_dirs = []
            for dirname in dirs:
                if dirname in ignore_dirs or dirname.startswith("."):
                    continue
                try:
                    authorized_path(Path(cur_root) / dirname)
                except (OSError, ValueError):
                    read_errors += 1
                else:
                    safe_dirs.append(dirname)
            dirs[:] = safe_dirs
            for f in filenames:
                if f.endswith((".py", ".ts", ".js", ".go", ".rs", ".cs")):
                    files_to_scan.append(Path(cur_root) / f)
                    if len(files_to_scan) > file_limit:
                        break
            if len(files_to_scan) > file_limit:
                break
        file_limit_reached = len(files_to_scan) > file_limit
        files_to_scan = files_to_scan[:file_limit]
    if path:
        file_limit_reached = False

    files_scanned = 0
    for fpath in files_to_scan:
        if len(results) >= result_probe_limit:
            break
        files_scanned += 1
        try:
            rel_p = str(fpath.relative_to(root_path)).replace("\\", "/")
            checked = authorized_path(fpath)
            before = checked.stat(follow_symlinks=False)
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(checked, flags)
            with os.fdopen(descriptor, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                    raise PermissionError("source identity changed")
                rechecked = authorized_path(fpath).stat(follow_symlinks=False)
                if (opened.st_dev, opened.st_ino) != (rechecked.st_dev, rechecked.st_ino):
                    raise PermissionError("source path changed before read")
                data = stream.read(4 * 1024 * 1024 + 1)
                after = os.fstat(stream.fileno())
            if len(data) > 4 * 1024 * 1024:
                raise ValueError("source exceeds read limit")
            current = authorized_path(fpath).stat(follow_symlinks=False)
            # Windows may expose different ctime semantics through an open
            # handle and a fresh path stat; do not reject stable files for it.
            identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns) + (() if os.name == "nt" else (value.st_ctime_ns,))
            if identity(opened) != identity(after) or identity(after) != identity(current):
                raise PermissionError("source changed during read")
            content = data.decode("utf-8", errors="replace")
        except (OSError, ValueError):
            read_errors += 1
            continue

        lines = content.splitlines()
        file_result_start = len(results)
        parse_failed = False

        if fpath.suffix == ".py":
            if target_pattern.startswith(("fn:", "function:", "class:", "call:")):
                target_name = target_pattern.split(":", 1)[1].strip().split(".")[-1]
                if target_name and re.search(rf"\b{re.escape(target_name)}\b", content, re.IGNORECASE) is None:
                    continue
            try:
                tree = ast.parse(content, filename=rel_p)
                for node in ast.walk(tree):
                    if len(results) >= result_probe_limit:
                        break

                    if target_pattern.startswith(("fn:", "function:", "class:")):
                        prefix, name = target_pattern.split(":", 1)
                        name = name.strip()
                        kinds = (ast.ClassDef,) if prefix == "class" else (ast.FunctionDef, ast.AsyncFunctionDef)
                        if isinstance(node, kinds) and node.name.lower() == name:
                            label = "class" if prefix == "class" else "function"
                            results.append({
                                "file": rel_p,
                                "line": node.lineno,
                                "structure": f"{label}:{name}",
                                "description": f"{label.capitalize()} declaration matching '{name}'",
                                "snippet": lines[node.lineno - 1].strip()[:120],
                            })
                    elif target_pattern in {"bare_except", "unhandled_exception", "missing_error_handling"}:
                        if isinstance(node, ast.Try):
                            for handler in node.handlers:
                                if len(results) >= result_probe_limit:
                                    break
                                if handler.type is None:
                                    snip = lines[handler.lineno - 1].strip() if handler.lineno <= len(lines) else ""
                                    results.append({
                                        "file": rel_p,
                                        "line": handler.lineno,
                                        "structure": "bare_except",
                                        "description": "Bare 'except:' catches all exceptions including SystemExit and KeyboardInterrupt",
                                        "snippet": snip,
                                    })
                                elif isinstance(handler.type, ast.Name) and handler.type.id in {"Exception", "BaseException"}:
                                    if len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass):
                                        snip = lines[handler.lineno - 1].strip() if handler.lineno <= len(lines) else ""
                                        results.append({
                                            "file": rel_p,
                                            "line": handler.lineno,
                                            "structure": "silent_except_pass",
                                            "description": "Silent 'except Exception: pass' swallows errors without logging",
                                            "snippet": snip,
                                        })

                    elif target_pattern in {"unclosed_resource", "open_without_with", "resource_leak"}:
                        if isinstance(node, ast.Assign):
                            if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "open":
                                snip = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
                                results.append({
                                    "file": rel_p,
                                    "line": node.lineno,
                                    "structure": "open_without_with",
                                    "description": "File opened with direct assignment rather than 'with open(...)' context manager",
                                    "snippet": snip,
                                })

                    elif target_pattern in {"async_without_await", "redundant_async"}:
                        if isinstance(node, ast.AsyncFunctionDef):
                            has_await = any(isinstance(child, (ast.Await, ast.AsyncWith, ast.AsyncFor)) for child in ast.walk(node))
                            if not has_await:
                                snip = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
                                results.append({
                                    "file": rel_p,
                                    "line": node.lineno,
                                    "structure": "async_without_await",
                                    "description": f"Async function '{node.name}' contains no await, async with, or async for expressions",
                                    "snippet": snip,
                                })

                    elif target_pattern.startswith("decorator:") or target_pattern.startswith("@"):
                        dec_target = target_pattern.split(":", 1)[-1].lstrip("@").strip()
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            for dec in node.decorator_list:
                                dec_id = ""
                                if isinstance(dec, ast.Name):
                                    dec_id = dec.id
                                elif isinstance(dec, ast.Attribute):
                                    dec_id = dec.attr
                                elif isinstance(dec, ast.Call):
                                    if isinstance(dec.func, ast.Name):
                                        dec_id = dec.func.id
                                    elif isinstance(dec.func, ast.Attribute):
                                        dec_id = dec.func.attr
                                if dec_target.lower() in dec_id.lower():
                                    snip = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
                                    results.append({
                                        "file": rel_p,
                                        "line": node.lineno,
                                        "structure": f"decorator:{dec_id}",
                                        "symbol": node.name,
                                        "description": f"Function/class '{node.name}' has matching decorator @{dec_id}",
                                        "snippet": snip,
                                    })

                    elif target_pattern.startswith("subclass:") or target_pattern.startswith("inherit:"):
                        sub_target = target_pattern.split(":", 1)[1].strip()
                        if isinstance(node, ast.ClassDef):
                            for base in node.bases:
                                base_id = ""
                                if isinstance(base, ast.Name):
                                    base_id = base.id
                                elif isinstance(base, ast.Attribute):
                                    base_id = base.attr
                                if sub_target.lower() in base_id.lower():
                                    snip = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
                                    results.append({
                                        "file": rel_p,
                                        "line": node.lineno,
                                        "structure": f"subclass:{base_id}",
                                        "symbol": node.name,
                                        "description": f"Class '{node.name}' inherits from '{base_id}'",
                                        "snippet": snip,
                                    })

                    elif target_pattern.startswith("call:"):
                        fn_target = target_pattern.split(":", 1)[1].strip()
                        if isinstance(node, ast.Call):
                            call_id = ""
                            if isinstance(node.func, ast.Name):
                                call_id = node.func.id
                            elif isinstance(node.func, ast.Attribute):
                                call_id = node.func.attr
                            if fn_target.lower() in call_id.lower():
                                snip = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
                                results.append({
                                    "file": rel_p,
                                    "line": node.lineno,
                                    "structure": f"call:{call_id}",
                                    "description": f"Call to '{call_id}'",
                                    "snippet": snip,
                                })
            except SyntaxError:
                parse_errors += 1
                parse_failed = True

        if (parse_failed or len(results) == file_result_start or fpath.suffix != ".py") and not (
            fpath.suffix == ".py" and target_pattern.startswith(("fn:", "function:", "class:"))
        ):
            for idx, line in enumerate(lines, 1):
                if len(results) >= result_probe_limit:
                    break
                raw_line = line.strip()
                if not raw_line or raw_line.startswith(("//", "#", "/*", "*")):
                    continue
                matched = False
                desc = ""
                struct_type = "text_pattern"

                # Multi-language JS/TS patterns
                if target_pattern in {"unhandled_promise", "catch_missing"} and ".then(" in raw_line and ".catch(" not in raw_line:
                    matched = True
                    struct_type = "unhandled_promise"
                    desc = "Promise .then() chained without .catch() handler"
                elif target_pattern in {"empty_catch", "silent_catch"} and (
                    re.search(r"catch\s*(?:\([^)]*\))?\s*\{\s*\}", raw_line)
                    or ("catch" in raw_line and "{" in raw_line and idx < len(lines) and lines[idx].strip() == "}")
                ):
                    matched = True
                    struct_type = "empty_catch"
                    desc = "Empty catch block swallowing errors silently"
                elif target_pattern in {"any_type", "ts_any"} and re.search(r":\s*any\b|\bas\s+any\b", raw_line):
                    matched = True
                    struct_type = "any_type"
                    desc = "TypeScript 'any' type bypasses static type verification"
                elif target_pattern in {"react_hook", "hook"} and re.search(r"\buse[A-Z][a-zA-Z0-9_]*\s*\(", raw_line):
                    matched = True
                    struct_type = "react_hook"
                    desc = "React hook invocation"

                # Go patterns
                elif target_pattern in {"goroutine_leak", "goroutine"} and re.search(r"\bgo\s+(?:func|[a-zA-Z0-9_.]+\()", raw_line):
                    matched = True
                    struct_type = "goroutine"
                    desc = "Goroutine spawned without explicit lifecycle management"
                elif target_pattern in {"error_ignored", "ignored_err"} and re.search(r"_,\s*err\s*:=|_\s*=\s*[a-zA-Z0-9_.]+\(", raw_line):
                    matched = True
                    struct_type = "error_ignored"
                    desc = "Error return value ignored or discarded with blank identifier"

                # Rust patterns
                elif target_pattern in {"unwrap_call", "unwrap"} and (".unwrap()" in raw_line or ".expect(" in raw_line):
                    matched = True
                    struct_type = "unwrap_call"
                    desc = "Potential panic via unchecked .unwrap() / .expect() call"
                elif target_pattern in {"unsafe_block", "unsafe"} and re.search(r"\bunsafe\s*\{", raw_line):
                    matched = True
                    struct_type = "unsafe_block"
                    desc = "Unsafe Rust block bypassing memory safety guarantees"
                elif target_pattern in {"todo_macro", "unimplemented"} and re.search(r"\b(?:todo!|unimplemented!)\(", raw_line):
                    matched = True
                    struct_type = "todo_macro"
                    desc = "Unfinished code via todo!() or unimplemented!() macro"

                # Universal prefix queries: fn:name, class:name, struct:name, interface:name
                elif target_pattern.startswith("fn:") or target_pattern.startswith("function:"):
                    fn_name = target_pattern.split(":", 1)[1].strip().lower()
                    if re.search(rf"\b(?:def|function|fn|func)\s+{re.escape(fn_name)}\b", raw_line, re.I):
                        matched = True
                        struct_type = f"function:{fn_name}"
                        desc = f"Function declaration matching '{fn_name}'"
                elif target_pattern.startswith("class:") or target_pattern.startswith("struct:") or target_pattern.startswith("interface:"):
                    prefix, ent_name = target_pattern.split(":", 1)
                    if re.search(rf"\b(?:class|struct|interface|type)\s+{re.escape(ent_name.strip())}\b", raw_line, re.I):
                        matched = True
                        struct_type = f"{prefix}:{ent_name.strip()}"
                        desc = f"{prefix.capitalize()} declaration matching '{ent_name.strip()}'"

                elif target_pattern in {"sql_injection"} and re.search(r"SELECT\s+.*\+\s*['\"]", raw_line, re.I):
                    matched = True
                    struct_type = "sql_injection"
                    desc = "Potential raw string concatenation in SQL statement"
                elif target_pattern in raw_line.lower():
                    matched = True
                    desc = f"Pattern match for '{target_pattern}'"

                if matched:
                    results.append({
                        "file": rel_p,
                        "line": idx,
                        "structure": struct_type,
                        "description": desc,
                        "snippet": raw_line[:120],
                    })

    returned_matches = results[:output_limit]
    truncation_reasons: list[str] = []
    if file_limit_reached:
        truncation_reasons.append("file_limit")
    if len(results) > output_limit:
        truncation_reasons.append("result_limit")
    if read_errors:
        truncation_reasons.append("read_errors")
    if parse_errors:
        truncation_reasons.append("parse_errors")
    return {
        "success": True,
        "root": str(root_path),
        "pattern": pattern,
        "count": len(returned_matches),
        "matches": returned_matches,
        "files_scanned": files_scanned,
        "truncated": bool(truncation_reasons),
        "truncation_reasons": truncation_reasons,
        "read_errors": read_errors,
        "parse_errors": parse_errors,
    }
