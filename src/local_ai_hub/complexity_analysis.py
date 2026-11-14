from __future__ import annotations

import ast
import os
import stat
import time
from pathlib import Path
from typing import Any

def compute_code_complexity(
    root: str,
    path: str | None = None,
    max_results: int = 20,
    include_tests: bool = False,
    *,
    is_symlink_or_reparse_point,
    is_test_file,
    is_root_archive_path,
) -> dict[str, Any]:
        """Compute McCabe cyclomatic and cognitive complexity metrics per function/method."""
        p_root = Path(root).expanduser().resolve(strict=False)
        if not p_root.is_dir():
            return {"success": False, "root": str(p_root), "error": "root directory does not exist"}
        max_entries = 20_000
        max_files = 50
        max_file_bytes = 1_048_576
        max_total_bytes = 16_777_216
        max_seconds = 5.0
        started = time.monotonic()
        deadline = started + max_seconds
        excluded_dirs = {
            ".git", ".venv", "venv", "node_modules", "__pycache__", "tool-envs",
            "state", "build", "dist", "archive", "archives", "history", "historical",
            "backup", "backups", "docs", "doc", "fixture", "fixtures", "vendor",
            "generated", "artifacts",
        }
        targets: list[tuple[int, str, Path]] = []
        errors: list[str] = []
        limits_hit: list[str] = []
        entries_visited = 0
        skipped_files = 0
        skipped_directories = 0
        eligible_files = 0
        total_bytes_read = 0
        complete = True

        def _incomplete(code: str) -> None:
            nonlocal complete
            complete = False
            if len(errors) < 20:
                errors.append(code)

        def _deadline_reached() -> bool:
            nonlocal complete
            if time.monotonic() < deadline:
                return False
            if "time" not in limits_hit:
                limits_hit.append("time")
            complete = False
            return True

        def _check_candidate_path(candidate: Path) -> Path:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(p_root)
            current = p_root
            for part in candidate.relative_to(p_root).parts:
                current = current / part
                if is_symlink_or_reparse_point(current):
                    raise ValueError("symbol scan path contains a link")
            return resolved

        if path:
            p = Path(path)
            if not p.is_absolute():
                p = p_root / p
            try:
                resolved = _check_candidate_path(p)
                if not resolved.is_file():
                    raise ValueError("requested path is not a regular file")
                targets.append((0, resolved.relative_to(p_root).as_posix(), p))
                eligible_files = 1
            except (OSError, ValueError):
                skipped_files += 1
                _incomplete("requested_path_unreadable_or_outside_root")
        else:
            pending = [p_root]
            while pending:
                if time.monotonic() >= deadline:
                    limits_hit.append("time")
                    complete = False
                    break
                current = pending.pop()
                try:
                    current = _check_candidate_path(current)
                    with os.scandir(current) as entries:
                        for entry in entries:
                            if time.monotonic() >= deadline:
                                limits_hit.append("time")
                                complete = False
                                pending.clear()
                                break
                            entries_visited += 1
                            if entries_visited > max_entries:
                                limits_hit.append("entries")
                                complete = False
                                pending.clear()
                                break
                            candidate = Path(entry.path)
                            if is_symlink_or_reparse_point(candidate):
                                if entry.is_dir(follow_symlinks=False):
                                    skipped_directories += 1
                                else:
                                    skipped_files += 1
                                _incomplete("linked_path_omitted")
                                continue
                            rel = candidate.relative_to(p_root).as_posix()
                            if is_root_archive_path(rel):
                                if entry.is_dir(follow_symlinks=False):
                                    skipped_directories += 1
                                elif entry.name.lower().endswith(".py"):
                                    skipped_files += 1
                                continue
                            if entry.name.lower() in excluded_dirs:
                                if entry.is_dir(follow_symlinks=False):
                                    skipped_directories += 1
                                elif entry.name.lower().endswith(".py"):
                                    skipped_files += 1
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                pending.append(candidate)
                                continue
                            if not entry.name.lower().endswith(".py"):
                                continue
                            if not include_tests and is_test_file(rel):
                                skipped_files += 1
                                continue
                            if not entry.is_file(follow_symlinks=False):
                                skipped_files += 1
                                _incomplete("non_regular_file_omitted")
                                continue
                            eligible_files += 1
                            parts = rel.split("/")
                            priority = 0 if parts[0].lower() == "src" else 1 if parts[0].lower() in {"app", "server", "lib", "libs", "packages", "tools"} else 2
                            targets.append((priority, rel.casefold(), candidate))
                except (OSError, ValueError):
                    _incomplete("directory_unreadable_or_outside_root")
            targets.sort(key=lambda item: (item[0], item[1], item[2].as_posix()))
            if len(targets) > max_files:
                skipped_files += len(targets) - max_files
                targets = targets[:max_files]
                limits_hit.append("files")
                complete = False

        results: list[dict[str, Any]] = []

        files_analyzed = 0
        parse_error_count = 0
        read_error_count = 0
        for _priority, _sort_path, p in targets:
            if time.monotonic() >= deadline:
                limits_hit.append("time")
                complete = False
                break
            try:
                resolved = _check_candidate_path(p)
                before = os.stat(p, follow_symlinks=False)
                if not stat.S_ISREG(before.st_mode):
                    skipped_files += 1
                    _incomplete("non_regular_file_omitted")
                    continue
                remaining_bytes = max_total_bytes - total_bytes_read
                if before.st_size > max_file_bytes or before.st_size > remaining_bytes:
                    skipped_files += 1
                    limits_hit.append("file_bytes" if before.st_size > max_file_bytes else "total_bytes")
                    complete = False
                    continue
                flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
                if getattr(os, "O_NOFOLLOW", 0):
                    flags |= os.O_NOFOLLOW
                fd = os.open(p, flags)
                try:
                    opened = os.fstat(fd)
                    if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                        skipped_files += 1
                        _incomplete("file_identity_changed_or_non_regular")
                        continue
                    source = os.fdopen(fd, "rb")
                    fd = -1
                finally:
                    if fd >= 0:
                        os.close(fd)
                with source:
                    read_limit = min(max_file_bytes, remaining_bytes)
                    raw_content = source.read(read_limit)
                    total_bytes_read += len(raw_content)
                    after = os.fstat(source.fileno())
                    current = os.stat(p, follow_symlinks=False)
                    current_path = _check_candidate_path(p)
                before_state = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
                after_state = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                if before_state != after_state or (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino) or current_path != resolved:
                    _incomplete("file_changed_during_scan")
                if after.st_size > max_file_bytes or after.st_size > read_limit:
                    limits_hit.append("file_bytes" if after.st_size > max_file_bytes else "total_bytes")
                    complete = False
                    skipped_files += 1
                    continue
                if len(raw_content) != after.st_size:
                    _incomplete("file_read_incomplete")
                    skipped_files += 1
                    continue
                content = raw_content.decode("utf-8", errors="replace")
            except Exception:
                skipped_files += 1
                read_error_count += 1
                _incomplete("file_parse_or_read_error")
                continue
            try:
                tree = ast.parse(content, filename=str(p))
            except Exception:
                skipped_files += 1
                parse_error_count += 1
                _incomplete("file_parse_error")
                continue
            files_analyzed += 1
            if _deadline_reached():
                break

            analysis_stopped = False
            for node in ast.walk(tree):
                if _deadline_reached():
                    analysis_stopped = True
                    break
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fn_name = node.name
                    lineno = node.lineno
                    cyclomatic = 1
                    cognitive = 0

                    def walk_cognitive(curr_node: ast.AST, depth: int) -> bool:
                        nonlocal cyclomatic, cognitive
                        if _deadline_reached():
                            return False
                        for child in ast.iter_child_nodes(curr_node):
                            if _deadline_reached():
                                return False
                            inc_depth = False
                            if isinstance(child, (ast.If, ast.While, ast.For, ast.AsyncFor)):
                                cyclomatic += 1
                                cognitive += (1 + depth)
                                inc_depth = True
                            elif isinstance(child, ast.ExceptHandler):
                                cyclomatic += 1
                                cognitive += (1 + depth)
                                inc_depth = True
                            elif isinstance(child, (ast.With, ast.AsyncWith, ast.Assert)):
                                cyclomatic += 1
                            elif isinstance(child, ast.BoolOp):
                                cyclomatic += max(0, len(child.values) - 1)
                                cognitive += max(0, len(child.values) - 1)
                            elif isinstance(child, ast.comprehension):
                                cyclomatic += 1 + len(child.ifs)
                                cognitive += (1 + depth)

                            if not walk_cognitive(child, depth + (1 if inc_depth else 0)):
                                return False
                        return True

                    if not walk_cognitive(node, 0):
                        analysis_stopped = True
                        break
                    risk = "high" if (cyclomatic >= 10 or cognitive >= 15) else "medium" if (cyclomatic >= 6 or cognitive >= 8) else "low"
                    results.append({
                        "name": fn_name,
                        "file": p.relative_to(p_root).as_posix() if p.is_relative_to(p_root) else str(p),
                        "line": lineno,
                        "cyclomatic_complexity": cyclomatic,
                        "cognitive_complexity": cognitive,
                        "risk": risk,
                    })
            if analysis_stopped:
                break

        results.sort(key=lambda x: (-x["cognitive_complexity"], -x["cyclomatic_complexity"]))
        scope = (
            "explicit in-root file"
            if path
            else f"bounded source-first Python files; include_tests={bool(include_tests)}; excludes listed generated, archive, documentation, fixture and cache directories"
        )
        limits = {
            "max_entries": max_entries,
            "max_files": max_files,
            "max_file_bytes": max_file_bytes,
            "max_total_bytes": max_total_bytes,
            "max_seconds": max_seconds,
        }
        return {
            "success": True,
            "root": str(p_root),
            "files_analyzed": files_analyzed,
            "total_functions": len(results),
            "high_risk_count": sum(1 for r in results if r["risk"] == "high"),
            "include_tests": bool(include_tests),
            "functions": results[:max(1, min(int(max_results), 100))],
            "complete": complete,
            "scope": scope,
            "limits": limits,
            "eligible_files": eligible_files,
            "skipped_files": skipped_files,
            "skipped_directories": skipped_directories,
            "parse_error_count": parse_error_count,
            "read_error_count": read_error_count,
            "coverage": {
                "complete": complete,
                "scope": scope,
                "deadline_kind": "cooperative",
                "entries_visited": entries_visited,
                "eligible_files": eligible_files,
                "files_analyzed": files_analyzed,
                "skipped_files": skipped_files,
                "skipped_directories": skipped_directories,
                "parse_error_count": parse_error_count,
                "read_error_count": read_error_count,
                "bytes_read": total_bytes_read,
                "limits_hit": sorted(set(limits_hit)),
                "errors": errors,
                "excluded_dirs": sorted(excluded_dirs),
            },
        }
