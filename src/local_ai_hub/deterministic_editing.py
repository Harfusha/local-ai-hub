from __future__ import annotations

import ast
from contextlib import closing
import io
import json
import keyword
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

from .api_spec_extraction import extract_api_spec as _extract_api_spec
from .circular_dependency_analysis import find_circular_dependencies as find_indexed_circular_dependencies
from .code_invariants import run_code_invariants
from .complexity_analysis import compute_code_complexity
from .dataset_generation import build_dataset
from .dead_code_detection import find_dead_code
from .deterministic_constants import (
    _SQLITE_DISCOVERY_MAX_ENTRIES,
    _SQLITE_DISCOVERY_MAX_SECONDS,
)
from .deterministic_test_paths import is_test_file as _is_test_file
from .json_utils import dumps as json_dumps
from .process_utils import hidden_run_kwargs, run_hidden
from .profile_digest import build_profile_digest
from .python_relations import find_python_relations
from .python_shell_injection import _python_shell_injection_lines
from .reparse_points import (
    _is_directory_reparse_point,
    _is_symlink_or_reparse_point,
)
from .repo_tools import is_root_archive_path
from .secret_scan_config import (
    _SECRET_SCAN_MAX_ENTRIES,
    _SECRET_SCAN_MAX_FILES,
    _SECRET_SCAN_MAX_FILE_BYTES,
    _SECRET_SCAN_MAX_FINDINGS,
    _SECRET_SCAN_MAX_LINE_BYTES,
    _SECRET_SCAN_MAX_SECONDS,
    _SECRET_SCAN_MAX_TOTAL_BYTES,
    _SECRET_SCAN_PATTERNS,
)
from .secret_scanning import scan_secrets
from .security_audit import run_security_audit
from .security_audit_patterns import (
    _SECURITY_AUDIT_SECRETS,
    _SECURITY_AUDIT_SMELLS,
    _pattern_match_lines,
    _yaml_load_match_lines,
)
from .source_outline import ast_outline as _source_ast_outline, fold_brace_blocks as _fold_brace_blocks
from .split_changes import run_split_changes
from .sqlite_counts import global_row_counts
from .sqlite_support import connect_sqlite


class DeterministicEditingMixin:
    def security_audit(self, root: str, limit: int = 50) -> dict[str, Any]:
        """Deterministic static security analysis (hardcoded secrets, unsafe deserialization, SQL injection)."""
        if type(limit) is not int or not 1 <= limit <= 100000:
            return {"success": False, "error": "limit must be an integer from 1 through 100000", "terminal": True, "retryable": False}
        return run_security_audit(
            self,
            root,
            limit,
            secret_patterns=_SECURITY_AUDIT_SECRETS,
            code_smell_patterns=_SECURITY_AUDIT_SMELLS,
            python_shell_injection_lines=_python_shell_injection_lines,
            yaml_load_match_lines=_yaml_load_match_lines,
            pattern_match_lines=_pattern_match_lines,
            path_type=Path,
            ast_module=ast,
            os_module=os,
            time_module=time,
        )

    def split_changes(
        self, root: str, changed_files: list[str] | None = None, *,
        base: str | None = None, head: str = "HEAD",
    ) -> dict[str, Any]:
        """Propose read-only component groups for worktree or committed changes."""
        return run_split_changes(
            self,
            root,
            changed_files,
            path_type=Path,
            subprocess_module=subprocess,
            hidden_run_kwargs_fn=hidden_run_kwargs,
            base=base,
            head=head,
            git_runner=run_hidden,
        )

    def synthesize_rules(self, root: str, limit: int = 10) -> dict[str, Any]:
        """Synthesize proactive coding and architecture rules from repository conventions."""
        resolved_root = Path(self._root(root))
        rules: list[dict[str, Any]] = []

        has_ruff = (resolved_root / "pyproject.toml").exists() or (resolved_root / "ruff.toml").exists()
        has_ts = (resolved_root / "tsconfig.json").exists()

        rules.append({
            "rule_id": "rule_bounded_execution",
            "title": "Always bound subprocesses and execution timeouts",
            "context": "System stability",
            "guidance": "Always specify bounded timeouts and use hidden_run_kwargs on Windows to avoid process orphans and GUI popups.",
            "confidence": 0.95,
        })

        rules.append({
            "rule_id": "rule_deterministic_first",
            "title": "Query deterministic indexes before neural models",
            "context": "Token & context efficiency",
            "guidance": "Use deterministic symbol index, ast refactoring, and code search before invoking local or cloud LLMs.",
            "confidence": 0.90,
        })

        if has_ts:
            rules.append({
                "rule_id": "rule_typescript_strict",
                "title": "TypeScript typecheck before committing",
                "context": "Type safety",
                "guidance": "Run `tsc --noEmit` with the agent host's native command tool before creating diffs or handoffs.",
                "confidence": 0.85,
            })

        if has_ruff:
            rules.append({
                "rule_id": "rule_python_ruff",
                "title": "Run ruff format and lint",
                "context": "Python styling",
                "guidance": "Run ruff format and lint with the agent host's native command tool before submitting PRs.",
                "confidence": 0.88,
            })

        return {
            "success": True,
            "root": str(resolved_root),
            "rule_count": len(rules),
            "rules": rules[:limit],
        }

    def code_invariants(self, root: str, path: str | None = None) -> dict[str, Any]:
        """Check Python source invariants; report unsupported files and syntax errors."""
        return run_code_invariants(
            self,
            root,
            path,
            path_type=Path,
            ast_module=ast,
            os_module=os,
            is_root_archive_path_fn=is_root_archive_path,
        )

    def generate_dataset(
        self,
        root: str,
        schema_or_model: dict[str, Any] | list[Any],
        count: int = 10,
        format: str = "json",
    ) -> dict[str, Any]:
        """Generate synthetic test datasets and seed data adhering to a field schema."""
        return build_dataset(
            self,
            root,
            schema_or_model,
            count,
            format,
            path_type=Path,
            json_dumps=json_dumps,
            io_module=io,
        )

    def profile_digest(self, profile_path: str, top_n: int = 15) -> dict[str, Any]:
        """Digest a cProfile / pstats binary profile or flamegraph trace into top bottleneck functions."""
        return build_profile_digest(
            profile_path,
            top_n,
            path_type=Path,
            json_module=json,
            math_module=math,
        )

    def _find_python_relations(
        self, root: str, symbol: str, limit: int, offset: int, direction: str,
    ) -> dict[str, Any]:
        return find_python_relations(
            self, root, symbol, limit, offset, direction, _is_symlink_or_reparse_point,
        )

    def find_callers(self, root: str, symbol: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Find Python call sites targeting a symbol, in stable bounded pages."""
        return self._find_python_relations(root, symbol, limit, offset, "callers")

    def find_callees(self, root: str, symbol: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Find Python calls made by a named function, in stable bounded pages."""
        return self._find_python_relations(root, symbol, limit, offset, "callees")

    def find_dead_code(self, root: str, limit: int = 50) -> dict[str, Any]:
        """Detect potentially dead/uncalled functions and classes in repository."""
        return find_dead_code(
            self,
            root,
            limit,
            path_type=Path,
            os_module=os,
            ast_module=ast,
        )

    @staticmethod
    def fold_brace_blocks(code: str, target_symbols: set[str] | None = None) -> str:
        return _fold_brace_blocks(code, target_symbols)

    def ast_outline(self, root: str, path: str) -> dict[str, Any]:
        return _source_ast_outline(self._root(root), path)

    def secret_scan(
        self,
        root: str,
        path: str | None = None,
        *,
        scan_git_history: bool = False,
        commit_depth: int = 20,
    ) -> dict[str, Any]:
        return scan_secrets(
            self,
            root,
            path,
            scan_git_history=scan_git_history,
            commit_depth=commit_depth,
            max_entries=_SECRET_SCAN_MAX_ENTRIES,
            max_files=_SECRET_SCAN_MAX_FILES,
            max_file_bytes=_SECRET_SCAN_MAX_FILE_BYTES,
            max_total_bytes=_SECRET_SCAN_MAX_TOTAL_BYTES,
            max_line_bytes=_SECRET_SCAN_MAX_LINE_BYTES,
            max_seconds=_SECRET_SCAN_MAX_SECONDS,
            max_findings=_SECRET_SCAN_MAX_FINDINGS,
            patterns=_SECRET_SCAN_PATTERNS,
            run_hidden_callable=run_hidden,
        )

    @staticmethod
    def _find_sqlite_database(p_root: Path) -> tuple[Path | None, bool]:
        """Find a SQLite file within bounded entry and time budgets."""
        ignored_dirs = {"node_modules", "venv", "tool-envs", "site-packages", ".venv"}
        sqlite_suffixes = {".sqlite3", ".db", ".sqlite"}
        started = time.monotonic()
        scanned_entries = 0
        scan_failed = False

        def note_scan_error(_error: OSError) -> None:
            nonlocal scan_failed
            scan_failed = True

        for current, dirnames, filenames in os.walk(
            p_root, topdown=True, onerror=note_scan_error, followlinks=False
        ):
            if time.monotonic() - started >= _SQLITE_DISCOVERY_MAX_SECONDS:
                return None, False
            current_path = Path(current)
            sqlite_files = sorted(
                filename for filename in filenames
                if Path(filename).suffix.lower() in sqlite_suffixes
            )
            if sqlite_files:
                return current_path / sqlite_files[0], True

            scanned_entries += len(dirnames) + len(filenames)
            if scanned_entries > _SQLITE_DISCOVERY_MAX_ENTRIES:
                return None, False
            kept_dirs: list[str] = []
            for dirname in dirnames:
                if dirname.startswith(".") or dirname.lower() in ignored_dirs:
                    continue
                child = current_path / dirname
                if _is_directory_reparse_point(child):
                    continue
                kept_dirs.append(dirname)
            dirnames[:] = sorted(kept_dirs)
        return None, not scan_failed

    def schema_inspect(self, root: str, db_path: str | None = None) -> dict[str, Any]:
        """Inspect SQLite database schema (tables, columns, indexes, foreign keys)."""
        p_root = Path(self._root(root))
        target_db: Path | None = None
        if db_path:
            p = Path(db_path)
            target_db = p if p.is_absolute() else p_root / p
            search_complete = True
        else:
            target_db, search_complete = self._find_sqlite_database(p_root)

        if not target_db or not target_db.is_file():
            if not search_complete:
                return {
                    "success": False,
                    "status_code": 422,
                    "terminal": True,
                    "retryable": False,
                    "database_search_complete": False,
                    "error": "SQLite database search reached a safety limit; provide db_path",
                }
            return {
                "success": False,
                "status_code": 404,
                "database_search_complete": True,
                "error": f"no SQLite database found in root: {root}",
            }

        try:
            resolved_db = target_db.resolve(strict=True)
            relative_db = resolved_db.relative_to(p_root)
        except (OSError, ValueError) as exc:
            return {"success": False, "status_code": 400, "error": f"database path is outside root or unavailable: {exc}"}

        tables: dict[str, Any] = {}
        try:
            database_uri = f"{resolved_db.as_uri()}?mode=ro"
            with closing(connect_sqlite(database_uri, uri=True, timeout_seconds=5.0, read_only=True)) as con:
                tbl_rows = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
                for (tbl_name,) in tbl_rows:
                    safe_tbl = tbl_name.replace('"', '""')
                    cols = con.execute(f'PRAGMA table_info("{safe_tbl}")').fetchall()
                    indexes = con.execute(f'PRAGMA index_list("{safe_tbl}")').fetchall()
                    fks = con.execute(f'PRAGMA foreign_key_list("{safe_tbl}")').fetchall()
                    tables[tbl_name] = {
                        "columns": [{"name": c[1], "type": c[2], "notnull": bool(c[3]), "pk": bool(c[5])} for c in cols],
                        "indexes": [idx[1] for idx in indexes],
                        "foreign_keys": [{"to_table": fk[2], "from_col": fk[3], "to_col": fk[4]} for fk in fks],
                    }
            return {
                "success": True,
                "db_path": str(relative_db).replace("\\", "/"),
                "table_count": len(tables),
                "tables": tables,
            }
        except Exception as exc:
            return {"success": False, "status_code": 500, "error": f"database inspection failed: {exc}"}

    def explain_query(self, root: str, query: str, db_path: str | None = None) -> dict[str, Any]:
        """Run EXPLAIN QUERY PLAN on an SQLite query to inspect execution strategy and indexes."""
        p_root = Path(self._root(root))
        target_db: Path | None = None
        if db_path:
            p = Path(db_path)
            target_db = p if p.is_absolute() else p_root / p
            search_complete = True
        else:
            target_db, search_complete = self._find_sqlite_database(p_root)

        if not target_db or not target_db.is_file():
            if not search_complete:
                return {
                    "success": False,
                    "status_code": 422,
                    "terminal": True,
                    "retryable": False,
                    "database_search_complete": False,
                    "error": "SQLite database search reached a safety limit; provide db_path",
                }
            return {
                "success": False,
                "status_code": 404,
                "database_search_complete": True,
                "error": "no SQLite database found for query explain",
            }

        if not query or not query.strip():
            return {"success": False, "status_code": 400, "error": "query cannot be empty"}

        clean_query = query.strip()
        if not clean_query.lower().startswith("select"):
            return {"success": False, "status_code": 400, "error": "only SELECT queries are allowed for explain_query"}
        if ";" in clean_query.rstrip(";"):
            return {"success": False, "status_code": 400, "error": "multiple statements are not permitted"}

        try:
            resolved_db = target_db.resolve(strict=True)
            relative_db = resolved_db.relative_to(p_root)
            with closing(connect_sqlite(resolved_db, timeout_seconds=5.0, read_only=True)) as con:
                rows = con.execute(f"EXPLAIN QUERY PLAN {clean_query}").fetchall()
                plan_items = [{"id": r[0], "parent": r[1], "detail": r[3]} for r in rows]
                uses_index = any("USING INDEX" in item["detail"] or "USING COVERING INDEX" in item["detail"] for item in plan_items)
                full_scan = any("SCAN TABLE" in item["detail"] for item in plan_items)

            return {
                "success": True,
                "db_path": str(relative_db).replace("\\", "/"),
                "query": clean_query,
                "uses_index": uses_index,
                "has_full_table_scan": full_scan,
                "plan": plan_items,
            }
        except Exception as exc:
            return {"success": False, "status_code": 500, "error": f"explain query failed: {exc}"}

    def env_compat(self, root: str) -> dict[str, Any]:
        """Analyze project manifests for OS, runtime, and build-tool dependencies."""
        p_root = Path(self._root(root))
        if not p_root.is_dir():
            return {"success": False, "error": f"root not found: {root}"}

        current_os = os.name
        results: dict[str, Any] = {
            "os": "windows" if current_os == "nt" else "posix",
            "python_version": sys.version.split()[0],
            "detected_manifests": [],
            "warnings": [],
            "toolchain_requirements": [],
        }

        pyproj = p_root / "pyproject.toml"
        if pyproj.is_file():
            results["detected_manifests"].append("pyproject.toml")
            content = pyproj.read_text(encoding="utf-8", errors="replace")
            if "maturin" in content or "setuptools-rust" in content:
                results["toolchain_requirements"].append("Rust compiler (cargo)")
            if "pybind11" in content or "cython" in content:
                results["toolchain_requirements"].append("C/C++ compiler toolchain (MSVC on Windows / GCC on Linux)")

        pkg_json = p_root / "package.json"
        if pkg_json.is_file():
            results["detected_manifests"].append("package.json")
            content = pkg_json.read_text(encoding="utf-8", errors="replace")
            if "node-gyp" in content:
                results["toolchain_requirements"].append("python + visual studio build tools (node-gyp)")

        cargo_toml = p_root / "Cargo.toml"
        if cargo_toml.is_file():
            results["detected_manifests"].append("Cargo.toml")
            if not shutil.which("cargo"):
                results["warnings"].append("Cargo.toml found but 'cargo' binary is not on system PATH")

        reqs = p_root / "requirements.txt"
        if reqs.is_file():
            results["detected_manifests"].append("requirements.txt")

        return {
            "success": True,
            **results,
            "python": results["python_version"],
            "dependencies": results["detected_manifests"],
            "ready": len(results["warnings"]) == 0,
        }

    def status(self, root: str | None = None) -> dict[str, Any]:
        now = time.monotonic()
        key = str(root or "__all__")
        if not hasattr(self, "_status_cache"):
            self._status_cache = {}
        cached = self._status_cache.get(key)
        if cached and now - cached["time"] < 5.0:
            return dict(cached["data"])
        try:
            # SQLite's WAL snapshot, rather than the index writer's Python lock,
            # isolates this read of committed metadata.
            with closing(self._connect()) as con:
                if root:
                    r = self._root(root); where = " WHERE root=?"; args = (r,)
                else:
                    where = ""; args = ()
                counts = {
                    "files": int(con.execute(f"SELECT COUNT(*) FROM files{where}", args).fetchone()[0]),
                    "facts": int(con.execute(f"SELECT COUNT(*) FROM facts{where}", args).fetchone()[0]),
                    "dependencies": int(con.execute(f"SELECT COUNT(*) FROM dependencies{where}", args).fetchone()[0]),
                    "scripts": int(con.execute(f"SELECT COUNT(*) FROM scripts{where}", args).fetchone()[0]),
                } if root else global_row_counts(con, ("files", "facts", "dependencies", "scripts"))
            res = {"success": True, "healthy": True, **counts, "stats": dict(self._stats)}
            if len(self._status_cache) > 64:
                oldest = sorted(self._status_cache.items(), key=lambda x: x[1].get("time", 0))[:32]
                for k, _ in oldest:
                    self._status_cache.pop(k, None)
            self._status_cache[key] = {"time": now, "data": res}
            return res
        except Exception as exc:
            return {"success": False, "healthy": False, "error": str(exc), "stats": dict(self._stats)}

    def find_circular_dependencies(
        self,
        root: str,
        language: str = "python",
        max_depth: int = 15,
        max_cycles: int = 50,
    ) -> dict[str, Any]:
        """Detect circular module import cycles in Python and JS/TS codebases."""
        return find_indexed_circular_dependencies(
            root, language, max_depth, max_cycles, self.code_index
        )

    def generate_types(self, root: str, file_path: str) -> dict[str, Any]:
        """Generate PEP 484 stub text without writing files."""
        max_source_bytes = 1_048_576
        try:
            p_root = Path(root).expanduser().resolve(strict=True)
            if not p_root.is_dir():
                raise ValueError("repository root is not a directory")
            target = Path(file_path).expanduser()
            if not target.is_absolute():
                target = p_root / target
            target = target.resolve(strict=True)
            try:
                target.relative_to(p_root)
            except ValueError:
                return {
                    "success": False,
                    "error": f"file is outside repository root: {file_path}",
                    "terminal": True,
                    "retryable": False,
                }
            if not target.is_file():
                return {
                    "success": False,
                    "error": f"file not found: {file_path}",
                    "terminal": True,
                    "retryable": False,
                }
            if target.stat().st_size > max_source_bytes:
                return {
                    "success": False,
                    "error": f"source file exceeds {max_source_bytes} byte limit",
                    "terminal": True,
                    "retryable": False,
                }
            with target.open("rb") as source_file:
                source_bytes = source_file.read(max_source_bytes + 1)
            if len(source_bytes) > max_source_bytes:
                return {
                    "success": False,
                    "error": f"source file exceeds {max_source_bytes} byte limit",
                    "terminal": True,
                    "retryable": False,
                }
            content = source_bytes.decode("utf-8", errors="replace")
            tree = ast.parse(content, filename=str(target))
        except (OSError, RuntimeError, ValueError) as exc:
            return {
                "success": False,
                "error": f"failed to resolve source file: {exc}",
                "terminal": True,
                "retryable": False,
            }
        except Exception as exc:
            return {
                "success": False,
                "error": f"failed to parse AST: {exc}",
                "terminal": True,
                "retryable": False,
            }

        stub_lines = ["from __future__ import annotations", "from typing import Any, Optional, Union, List, Dict, Tuple, Callable", ""]
        
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
                args = ast.unparse(node.args) if hasattr(ast, "unparse") else "..."
                ret = f" -> {ast.unparse(node.returns)}" if hasattr(ast, "unparse") and node.returns else " -> Any"
                stub_lines.append(f"{prefix}def {node.name}({args}){ret}: ...")
                stub_lines.append("")
            elif isinstance(node, ast.ClassDef):
                bases = f"({', '.join(ast.unparse(b) for b in node.bases)})" if hasattr(ast, "unparse") and node.bases else ""
                stub_lines.append(f"class {node.name}{bases}:")
                has_methods = False
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        has_methods = True
                        prefix = "    async " if isinstance(item, ast.AsyncFunctionDef) else "    "
                        args = ast.unparse(item.args) if hasattr(ast, "unparse") else "..."
                        ret = f" -> {ast.unparse(item.returns)}" if hasattr(ast, "unparse") and item.returns else " -> Any"
                        stub_lines.append(f"{prefix}def {item.name}({args}){ret}: ...")
                if not has_methods:
                    stub_lines.append("    ...")
                stub_lines.append("")

        stub_content = "\n".join(stub_lines).strip() + "\n"

        return {
            "success": True,
            "source_file": str(target),
            "stub_file": None,
            "stub_content": stub_content,
            "stub_lines": len(stub_lines),
        }

    def code_complexity(
        self, root: str, path: str | None = None, max_results: int = 20, include_tests: bool = False
    ) -> dict[str, Any]:
        return compute_code_complexity(
            root,
            path,
            max_results,
            include_tests,
            is_symlink_or_reparse_point=_is_symlink_or_reparse_point,
            is_test_file=_is_test_file,
            is_root_archive_path=is_root_archive_path,
        )

    def extract_api_spec(self, root: str, framework: str | None = None) -> dict[str, Any]:
        return _extract_api_spec(
            root,
            framework,
            repo_tools=getattr(self, "repo_tools", None),
        )

    def slice_dependency_graph(self, root: str, symbol: str, path: str | None = None, depth: int = 2) -> dict[str, Any]:
        """Extract a minimal AST dependency slice for a target symbol, saving context tokens."""
        if not isinstance(symbol, str) or not symbol.isidentifier() or keyword.iskeyword(symbol):
            return {"success": False, "status_code": 400, "error": "symbol must be a valid Python identifier"}
        p_root = Path(root).expanduser().resolve(strict=False)
        skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__"}

        target_file: Path | None = None
        target_node: ast.AST | None = None
        file_lines: list[str] = []

        files_to_check: list[Path] = []
        if path:
            p = Path(path)
            if not p.is_absolute():
                p = p_root / p
            try:
                p = p.resolve(strict=False)
                p.relative_to(p_root)
            except (OSError, RuntimeError, ValueError):
                return {"success": False, "status_code": 400, "error": "path must resolve inside the repository root"}
            if p.is_file():
                files_to_check.append(p)
        else:
            for current_root, directories, filenames in os.walk(p_root):
                directories[:] = sorted(directory for directory in directories if directory not in skip_dirs)
                files_to_check.extend(
                    Path(current_root) / filename
                    for filename in sorted(filenames)
                    if filename.lower().endswith(".py")
                )

        for p in files_to_check:
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(content, filename=str(p))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol:
                        target_file = p
                        target_node = node
                        file_lines = content.splitlines()
                        break
            except Exception:
                continue
            if target_node:
                break

        if not target_node or not target_file:
            return {"success": False, "error": f"symbol '{symbol}' not found"}

        referenced_names: set[str] = set()
        for sub in ast.walk(target_node):
            if isinstance(sub, ast.Call):
                if isinstance(sub.func, ast.Name):
                    referenced_names.add(sub.func.id)
                elif isinstance(sub.func, ast.Attribute):
                    referenced_names.add(sub.func.attr)

        snippets: list[str] = []
        target_code = "\n".join(file_lines[target_node.lineno - 1: getattr(target_node, "end_lineno", target_node.lineno + 10)])
        snippets.append(f"# === Target Symbol: {symbol} ({target_file.name}:{target_node.lineno}) ===\n{target_code}")

        found_deps: list[str] = []
        for dep_name in sorted(referenced_names):
            if dep_name == symbol or len(dep_name) <= 2:
                continue
            for p in [target_file] + files_to_check[:10]:
                try:
                    c = p.read_text(encoding="utf-8", errors="replace")
                    t = ast.parse(c, filename=str(p))
                    for n in ast.walk(t):
                        if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == dep_name:
                            lines = c.splitlines()
                            dep_code = "\n".join(lines[n.lineno - 1: getattr(n, "end_lineno", n.lineno + 15)])
                            snippets.append(f"# --- Dependency: {dep_name} ({p.name}:{n.lineno}) ---\n{dep_code}")
                            found_deps.append(dep_name)
                            break
                except Exception:
                    continue
                if dep_name in found_deps:
                    break

        sliced_code = "\n\n".join(snippets)
        total_original_chars = sum(len(f.read_text(encoding="utf-8", errors="replace")) for f in [target_file])
        token_savings = max(0.0, round((1.0 - (len(sliced_code) / max(1, total_original_chars))) * 100, 1))

        return {
            "success": True,
            "symbol": symbol,
            "file": str(target_file.relative_to(p_root) if target_file.is_relative_to(p_root) else target_file),
            "line": target_node.lineno,
            "dependencies_found": found_deps,
            "sliced_code": sliced_code,
            "slice_chars": len(sliced_code),
            "token_savings_percent": token_savings,
        }

