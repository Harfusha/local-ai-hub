from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path
import stat
import subprocess
from typing import Any

from .batch_replace_dirty_hunks import parse_dirty_hunks
from .deterministic_constants import (
    _MAX_SCHEMA_DB_BYTES,
    _MAX_SCHEMA_DB_COLUMNS,
    _MAX_SCHEMA_DB_TABLES,
    _MAX_SCHEMA_FILE_BYTES,
    _MAX_SCHEMA_MIGRATION_DB_BYTES,
    _MAX_SCHEMA_SCAN_SECONDS,
    _MAX_SCHEMA_TOTAL_BYTES,
    _SCHEMA_DB_TIMEOUT_SECONDS,
)
from .deterministic_test_paths import is_test_file as _is_test_file
from .migration_drift import detect_migration_drift
from .process_utils import canonical_root, hidden_run_kwargs
from .reparse_points import _is_symlink_or_reparse_point
from .schema_file_bounds import _bounded_schema_files
from .sqlite_support import connect_sqlite
from .state_paths import configured_state_dir
from .structural_search import search_structurally


class DeterministicSearchMixin:
    def migration_drift(self, root: str, db_path: str | None = None) -> dict[str, Any]:
        return detect_migration_drift(
            root,
            db_path,
            bounded_schema_files=_bounded_schema_files,
            connect_sqlite_fn=connect_sqlite,
            max_schema_db_bytes=_MAX_SCHEMA_DB_BYTES,
            schema_db_timeout_seconds=_SCHEMA_DB_TIMEOUT_SECONDS,
            max_schema_scan_seconds=_MAX_SCHEMA_SCAN_SECONDS,
            max_schema_db_tables=_MAX_SCHEMA_DB_TABLES,
            max_schema_db_columns=_MAX_SCHEMA_DB_COLUMNS,
            max_schema_migration_db_bytes=_MAX_SCHEMA_MIGRATION_DB_BYTES,
            max_schema_file_bytes=_MAX_SCHEMA_FILE_BYTES,
            max_schema_total_bytes=_MAX_SCHEMA_TOTAL_BYTES,
        )

    def package_audit(self, root: str, lockfile_path: str | None = None) -> dict[str, Any]:
        from .dependency_audit import MAX_MANIFEST_BYTES, audit_manifest
        try:
            lexical_root = Path(root).expanduser()
            if not lexical_root.is_absolute():
                raise ValueError("repository root must be absolute")
            p_root = lexical_root.resolve(strict=True)
            if not p_root.is_dir():
                raise ValueError("repository root must be a directory")
            target = None
            if lockfile_path:
                candidate = Path(lockfile_path)
                target = candidate if candidate.is_absolute() else p_root / candidate
            else:
                for name in ("poetry.lock", "requirements.txt", "package-lock.json", "composer.lock", "yarn.lock", "pnpm-lock.yaml", "Cargo.lock", "uv.lock", "pyproject.toml"):
                    candidate = p_root / name
                    if candidate.exists() or candidate.is_symlink():
                        target = candidate
                        break
            if target is None:
                raise ValueError("no supported dependency manifest or lockfile found in root")
            relative = target.relative_to(p_root)
            if ".." in relative.parts:
                raise PermissionError("manifest must stay inside repository root")
            cursor = p_root
            for part in relative.parts:
                cursor = cursor / part
                if _is_symlink_or_reparse_point(cursor):
                    raise PermissionError("manifest cannot traverse symlinks or reparse points")
            target = target.resolve(strict=True)
            target.relative_to(p_root)
            before = target.stat(follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_MANIFEST_BYTES:
                raise ValueError("manifest must be a regular file within the byte limit")
            descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
            with os.fdopen(descriptor, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino) or not stat.S_ISREG(opened.st_mode):
                    raise PermissionError("manifest changed during authorization")
                data = stream.read(MAX_MANIFEST_BYTES + 1)
            if len(data) > MAX_MANIFEST_BYTES:
                raise ValueError("manifest exceeded byte limit")
            return audit_manifest(target, data.decode("utf-8"))
        except (OSError, RuntimeError, ValueError, UnicodeError):
            return {"success": False, "status": "invalid", "parse_complete": False,
                    "advisory_complete": False, "error": "manifest unavailable or outside permitted repository input",
                    "error_code": "package_manifest_unavailable", "status_code": 422,
                    "terminal": True, "retryable": False}

    def structural_search(
        self,
        root: str,
        pattern: str,
        path: str | None = None,
        max_results: int = 30,
        file_offset: int = 0,
        match_offset: int = 0,
        expected_revision: str | None = None,
    ) -> dict[str, Any]:
        """Syntax-aware structural code search across Python and multi-language repositories."""
        return search_structurally(
            root,
            pattern,
            path=path,
            max_results=max_results,
            file_offset=file_offset,
            match_offset=match_offset,
            expected_revision=expected_revision,
            is_symlink_or_reparse_point=_is_symlink_or_reparse_point,
        )

    def context_budget(
        self,
        root: str,
        files: list[str] | None = None,
        max_tokens: int = 4000,
    ) -> dict[str, Any]:
        """Calculates token load per file and recommends surgical slices to fit within context budget."""
        canon_root = canonical_root(root)
        root_path = Path(canon_root)
        if not root_path.is_dir():
            return {"success": False, "error": f"invalid root directory: {root}"}

        from .code_tokens import count_code_tokens
        from .project_config import resolve_project_context
        settings = resolve_project_context(canon_root, configured_state_dir(self.config, create=False)).settings
        target_files = list(dict.fromkeys(files or []))
        if not target_files:
            target_files = [path.relative_to(root_path).as_posix()
                            for path in self.repo_tools.iter_files(canon_root, max_files=15)]
        omitted_files: list[dict[str, str]] = []
        bytes_read = 0
        all_exact = True
        if len(target_files) > 64:
            omitted_files.append({"path": "", "reason": "file_count_limit"})
        target_files = target_files[:64]

        file_breakdown: list[dict[str, Any]] = []
        total_chars = 0
        total_tokens = 0
        all_compressible_regions: list[dict[str, Any]] = []

        for rel in target_files:
            fpath = root_path / rel
            try:
                fpath.resolve(strict=True).relative_to(root_path)
                if not self.repo_tools._project_file_allowed(root_path, fpath, settings):
                    raise ValueError("path policy")
                limit = min(2_000_000, self.repo_tools.max_file_bytes, 8_000_000 - bytes_read)
                with fpath.open("rb") as handle:
                    raw = handle.read(max(0, limit) + 1)
                if len(raw) > limit:
                    raise ValueError("source budget")
                bytes_read += len(raw)
                content = raw.decode("utf-8", errors="replace")
            except (OSError, ValueError):
                omitted_files.append({"path": str(rel)[:240], "reason": "source_unavailable_or_outside_budget"})
                continue

            chars = len(content)
            token_count = count_code_tokens(content)
            tokens = int(token_count["tokens"])
            all_exact = all_exact and bool(token_count["exact"])
            total_chars += chars
            total_tokens += tokens

            lines = content.splitlines()
            compressible: list[dict[str, Any]] = []

            in_docstring = False
            doc_start = 0
            for idx, line in enumerate(lines, 1):
                s = line.strip()
                if '"""' in s or "'''" in s:
                    if not in_docstring:
                        in_docstring = True
                        doc_start = idx
                    else:
                        in_docstring = False
                        if idx - doc_start > 3:
                            compressible.append({
                                "file": rel,
                                "type": "docstring",
                                "start_line": doc_start,
                                "end_line": idx,
                                "tokens_saved": int((idx - doc_start) * 8),
                            })
                elif s.startswith("import ") or s.startswith("from "):
                    compressible.append({
                        "file": rel,
                        "type": "import_block",
                        "start_line": idx,
                        "end_line": idx,
                        "tokens_saved": 5,
                    })

            all_compressible_regions.extend(compressible[:5])

            file_breakdown.append({
                "path": rel,
                "lines": len(lines),
                "chars": chars,
                "est_tokens": tokens,
                "token_count_provenance": token_count,
                "compressible_regions_count": len(compressible),
            })

        exceeded = total_tokens > max_tokens
        recommended_slices: list[dict[str, Any]] = []
        if exceeded and file_breakdown:
            token_budget_per_file = max(100, int(max_tokens / len(file_breakdown)))
            for fb in file_breakdown:
                allowed_lines = min(fb["lines"], int(token_budget_per_file / 6))
                recommended_slices.append({
                    "path": fb["path"],
                    "slice": f"L1-L{allowed_lines}",
                    "est_slice_tokens": min(fb["est_tokens"], token_budget_per_file),
                })

        return {
            "success": True,
            "root": str(root_path),
            "max_tokens": max_tokens,
            "total_files": len(file_breakdown),
            "total_tokens": total_tokens,
            "token_count_provenance": {"encoding": "o200k_base", "exact": all_exact,
                                       "scope": "sum_of_decoded_file_counts"},
            "omitted_files": omitted_files,
            "complete": not omitted_files,
            "slice_recommendations_estimated": True,
            "budget_exceeded": exceeded,
            "file_breakdown": file_breakdown,
            "compressible_regions": all_compressible_regions[:15],
            "recommended_slices": recommended_slices,
            "compression_achievable_ratio": round(min(0.8, 1.0 - (max_tokens / max(1, total_tokens))), 2) if exceeded else 0.0,
        }

    def reachability_dead_code(
        self,
        root: str,
        entrypoints: list[str] | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Perform whole-repository call-graph reachability analysis from entry points to identify globally unused code."""
        root_path = Path(root).expanduser().resolve(strict=False)
        if not root_path.is_dir():
            return {"success": False, "error": f"Root directory does not exist: {root_path}"}

        ep_candidates = list(entrypoints or [])
        all_py_files: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(root_path):
            dirnames[:] = [d for d in dirnames if not d.startswith((".", "node_modules", "venv", "__pycache__", "build", "dist"))]
            for fn in filenames:
                p = Path(dirpath) / fn
                relative_path = p.relative_to(root_path)
                if p.suffix.lower() == ".py" and not _is_test_file(relative_path.as_posix()):
                    all_py_files.append(p)
                    if not entrypoints and fn.lower() in ("main.py", "app.py", "cli.py", "__main__.py", "server.py"):
                        ep_candidates.append(relative_path.as_posix())

        if not ep_candidates and all_py_files:
            ep_candidates.append(str(all_py_files[0].relative_to(root_path)).replace("\\", "/"))

        defs: dict[str, dict[str, Any]] = {}
        defs_by_name: dict[str, list[str]] = {}
        module_calls: dict[str, set[str]] = {}
        parse_errors: list[str] = []

        for p in all_py_files:
            rel = str(p.relative_to(root_path)).replace("\\", "/")
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                parse_errors.append(rel)
                continue

            file_calls: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    name = node.name
                    if not name.startswith("__"):
                        symbol_id = f"{rel}:{node.lineno}:{name}"
                        defs[symbol_id] = {"name": name, "file": rel, "line": node.lineno, "kind": type(node).__name__}
                        defs_by_name.setdefault(name, []).append(symbol_id)
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        file_calls.add(node.func.id)
                    elif isinstance(node.func, ast.Attribute):
                        file_calls.add(node.func.attr)
                elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    file_calls.add(node.id)
            module_calls[rel] = file_calls

        from .reachability_analysis import analyze_reachability
        ambiguous_names, reachable, ambiguous_symbols, unreachable = analyze_reachability(
            defs, defs_by_name, module_calls, ep_candidates
        )
        warnings = []
        if ambiguous_names:
            warnings.append("Duplicate symbol names make reachability ambiguous; affected symbols were excluded from reachable and dead-code counts.")
        if parse_errors:
            warnings.append("Some Python files could not be parsed; reachability results may be incomplete.")
        truncated = len(unreachable) > limit or len(ambiguous_symbols) > limit

        return {
            "success": True,
            "complete": not ambiguous_names and not parse_errors,
            "root": str(root_path),
            "entrypoints": ep_candidates,
            "total_symbols": len(defs),
            "reachable_symbols_count": len(reachable),
            "ambiguous_symbols_count": len(ambiguous_symbols),
            "ambiguous_symbols": ambiguous_symbols[:limit],
            "unreachable_symbols_count": len(unreachable),
            "unreachable_symbols": unreachable[:limit],
            "dead_code_count": len(unreachable),
            "truncated": truncated,
            "warnings": warnings,
        }

    def ast_mutation_test(
        self,
        root: str,
        target_file: str,
        diff: str | None = None,
    ) -> dict[str, Any]:
        """Generate syntax-aware AST mutation candidates to measure regression test coverage and test suite strength."""
        root_path = Path(root).expanduser().resolve(strict=False)
        p = (root_path / target_file) if not Path(target_file).is_absolute() else Path(target_file)
        if not p.is_file():
            return {"success": False, "error": f"File not found: {p}"}

        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(content)
        except Exception as exc:
            return {"success": False, "error": f"AST parse failed: {exc}"}

        mutants: list[dict[str, Any]] = []
        mutant_id = 1

        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for op in node.ops:
                    orig_op = type(op).__name__
                    repl_op = "NotEq" if orig_op == "Eq" else ("Eq" if orig_op == "NotEq" else ("GtE" if orig_op == "Lt" else "Lt"))
                    mutants.append({
                        "id": f"MUT_{mutant_id:03d}",
                        "type": "comparison_boundary",
                        "line": getattr(node, "lineno", 0),
                        "original": orig_op,
                        "mutant": repl_op,
                        "description": f"Invert {orig_op} comparison to {repl_op} at L{getattr(node, 'lineno', 0)}",
                    })
                    mutant_id += 1
            elif isinstance(node, ast.BinOp):
                orig_op = type(node.op).__name__
                if orig_op in ("Add", "Sub"):
                    repl_op = "Sub" if orig_op == "Add" else "Add"
                    mutants.append({
                        "id": f"MUT_{mutant_id:03d}",
                        "type": "arithmetic_inversion",
                        "line": getattr(node, "lineno", 0),
                        "original": orig_op,
                        "mutant": repl_op,
                        "description": f"Swap arithmetic {orig_op} to {repl_op} at L{getattr(node, 'lineno', 0)}",
                    })
                    mutant_id += 1
            elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
                mutants.append({
                    "id": f"MUT_{mutant_id:03d}",
                    "type": "boolean_flip",
                    "line": getattr(node, "lineno", 0),
                    "original": str(node.value),
                    "mutant": str(not node.value),
                    "description": f"Flip boolean constant {node.value} to {not node.value} at L{getattr(node, 'lineno', 0)}",
                })
                mutant_id += 1

        return {
            "success": True,
            "target_file": str(p.relative_to(root_path) if p.is_relative_to(root_path) else p),
            "mutants_count": len(mutants),
            "mutants": mutants[:50],
            "vulnerability_index": round(min(1.0, len(mutants) / 20.0), 2),
        }

    def generate_type_stubs(
        self,
        root: str,
        file_path: str,
    ) -> dict[str, Any]:
        """Generate clean .pyi or .d.ts type interface stubs from source AST."""
        root_path = Path(root).expanduser().resolve(strict=False)
        p = (root_path / file_path) if not Path(file_path).is_absolute() else Path(file_path)
        if not p.is_file():
            return {"success": False, "error": f"File not found: {p}"}

        content = p.read_text(encoding="utf-8", errors="ignore")
        if p.suffix.lower() == ".py":
            try:
                tree = ast.parse(content)
            except Exception as exc:
                return {"success": False, "error": f"Failed to parse python AST: {exc}"}

            stubs: list[str] = ["from __future__ import annotations", "from typing import Any, Optional, Union, Callable\n"]
            count = 0
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    stubs.append(ast.unparse(node))
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    count += 1
                    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                    args_str = ast.unparse(node.args)
                    ret_str = f" -> {ast.unparse(node.returns)}" if node.returns else " -> Any"
                    stubs.append(f"{prefix} {node.name}({args_str}){ret_str}: ...")
                elif isinstance(node, ast.ClassDef):
                    count += 1
                    bases = f"({', '.join(ast.unparse(b) for b in node.bases)})" if node.bases else ""
                    stubs.append(f"class {node.name}{bases}:")
                    methods_found = False
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            methods_found = True
                            count += 1
                            prefix = "async def" if isinstance(item, ast.AsyncFunctionDef) else "def"
                            args_str = ast.unparse(item.args)
                            ret_str = f" -> {ast.unparse(item.returns)}" if item.returns else " -> Any"
                            stubs.append(f"    {prefix} {item.name}({args_str}){ret_str}: ...")
                    if not methods_found:
                        stubs.append("    ...")

            stub_content = "\n".join(stubs) + "\n"
            return {
                "success": True,
                "file": file_path,
                "stub_type": "pyi",
                "symbols_annotated": count,
                "stub_content": stub_content,
            }
        else:
            lines = content.splitlines()
            declarations: list[str] = []
            for line in lines:
                s = line.strip()
                if s.startswith(("export function ", "export class ", "export interface ", "export type ")):
                    declarations.append(s.rstrip("{").strip() + ";")
            return {
                "success": True,
                "file": file_path,
                "stub_type": "d.ts",
                "symbols_annotated": len(declarations),
                "stub_content": "\n".join(declarations) + "\n",
            }

    @staticmethod
    def ast_diff(old_code: str, new_code: str) -> dict[str, Any]:
        """Classify bounded Python structural changes without executing source."""
        from .ast_diff import ast_diff

        return ast_diff(old_code, new_code)

    def skeletonize_code(
        self,
        code: str = "",
        target_symbols: list[str] | None = None,
        keep_imports: bool = True,
        *,
        root: str = "",
        path: str = "",
    ) -> dict[str, Any]:
        """Fold non-target function and method bodies into '...' to radically save prompt tokens while preserving AST outline."""
        if path and not code:
            indexed = getattr(self.code_index, "indexed_skeleton", None)
            if not callable(indexed) or target_symbols:
                return {"success": False, "terminal": True, "retryable": False,
                        "error_code": "indexed_skeleton_unavailable",
                        "error": "indexed outline requires an active index and no retained target bodies; otherwise supply source text"}
            return indexed(root, path)
        try:
            tree = ast.parse(code)
        except Exception:
            if "{" in code and "}" in code:
                skeleton = self.fold_brace_blocks(code, set(target_symbols or []))
                orig_len = len(code)
                skel_len = len(skeleton)
                ratio = round((orig_len - skel_len) / max(1, orig_len), 3)
                return {
                    "success": True,
                    "original_chars": orig_len,
                    "skeleton_chars": skel_len,
                    "savings_ratio": max(0.0, ratio),
                    "skeleton_code": skeleton,
                    "polyglot": True,
                }
            return {"success": True, "skeleton_code": code, "original_chars": len(code), "skeleton_chars": len(code), "savings_ratio": 0.0}

        targets = set(target_symbols or [])

        class _SkeletonTransformer(ast.NodeTransformer):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
                self.generic_visit(node)
                if not targets or node.name not in targets:
                    doc = ast.get_docstring(node)
                    new_body: list[ast.stmt] = []
                    if doc:
                        new_body.append(ast.Expr(value=ast.Constant(value=doc)))
                    new_body.append(ast.Expr(value=ast.Constant(value=Ellipsis)))
                    node.body = new_body
                return node

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
                self.generic_visit(node)
                if not targets or node.name not in targets:
                    doc = ast.get_docstring(node)
                    new_body: list[ast.stmt] = []
                    if doc:
                        new_body.append(ast.Expr(value=ast.Constant(value=doc)))
                    new_body.append(ast.Expr(value=ast.Constant(value=Ellipsis)))
                    node.body = new_body
                return node

        transformer = _SkeletonTransformer()
        transformed = transformer.visit(tree)
        ast.fix_missing_locations(transformed)

        try:
            skeleton = ast.unparse(transformed)
        except Exception:
            skeleton = code

        orig_len = len(code)
        skel_len = len(skeleton)
        ratio = round((orig_len - skel_len) / max(1, orig_len), 3)

        return {
            "success": True,
            "original_chars": orig_len,
            "skeleton_chars": skel_len,
            "savings_ratio": max(0.0, ratio),
            "skeleton_code": skeleton,
        }

    def batch_replace(
        self,
        root: str,
        edits: list[dict[str, Any]],
        dry_run: bool = False,
        *,
        owned_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """Apply multiple surgical string replacements across one or more files atomically with rollback."""
        p_root = Path(self._root(root)).resolve()
        if not edits or not isinstance(edits, list):
            return {"success": False, "error": "edits must be a non-empty list of replacement operations"}

        owned_scopes: list[Path] = []
        for owned_path in owned_paths or []:
            if not isinstance(owned_path, str) or not owned_path or owned_path != owned_path.strip() or "\x00" in owned_path:
                return {"success": False, "applied": False, "error": "invalid verified lease path"}
            scope = (p_root / owned_path).resolve()
            if not scope.is_relative_to(p_root):
                return {"success": False, "applied": False, "error": "verified lease path escapes project root"}
            owned_scopes.append(scope)

        def covered_by_verified_lease(target_path: Path) -> bool:
            for scope in owned_scopes:
                try:
                    target_path.relative_to(scope)
                    return True
                except ValueError:
                    continue
            return False

        # 1. Validate edit structures, resolve target files, and capture dirty hunks.
        resolved_files: dict[str, Path] = {}
        dirty_hunks: dict[Path, list[tuple[int, int]] | None] = {}
        for idx, edit in enumerate(edits):
            if not isinstance(edit, dict):
                return {"success": False, "error": f"edit #{idx} is not an object"}
            p_str = edit.get("path") or edit.get("file")
            old_str = edit.get("old") or edit.get("target") or edit.get("target_content")
            new_str = edit.get("new") if "new" in edit else (edit.get("replacement") or edit.get("replacement_content"))
            if not p_str or old_str is None or new_str is None:
                return {"success": False, "error": f"edit #{idx} missing path, old, or new"}
            
            p_candidate = (p_root / p_str).resolve()
            if not p_candidate.is_relative_to(p_root):
                return {"success": False, "error": f"path '{p_str}' escapes project root"}
            if not p_candidate.is_file():
                return {"success": False, "error": f"file not found: {p_str}"}
            rel_candidate = str(p_candidate.relative_to(p_root)).replace("\\", "/")
            try:
                status = subprocess.run(
                    ["git", "-C", str(p_root), "status", "--porcelain", "--", rel_candidate],
                    capture_output=True, check=False, timeout=5, **hidden_run_kwargs(),
                )
            except (OSError, subprocess.SubprocessError) as exc:
                return {"success": False, "applied": False, "error": f"unable to inspect Git status for {p_str}: {exc}", "path": p_str}
            if status.returncode == 0 and status.stdout.strip():
                if status.stdout.lstrip().startswith(b"??"):
                    dirty_hunks[p_candidate] = [(1, 2**31 - 1)]
                else:
                    try:
                        diff = subprocess.run(
                            ["git", "-C", str(p_root), "diff", "--no-ext-diff", "--unified=0", "HEAD", "--", rel_candidate],
                            capture_output=True, check=False, timeout=5, **hidden_run_kwargs(),
                        )
                    except (OSError, subprocess.SubprocessError) as exc:
                        return {"success": False, "applied": False, "error": f"unable to inspect Git diff for {p_str}: {exc}", "path": p_str}
                    if diff.returncode != 0:
                        return {"success": False, "applied": False, "error": f"Git diff failed for {p_str}: {diff.stderr.decode('utf-8', errors='replace')[:300]}", "path": p_str}
                    dirty_hunks[p_candidate] = parse_dirty_hunks(diff.stdout)
            elif status.returncode != 0:
                stderr = status.stderr.decode("utf-8", errors="replace")
                if "not a git repository" not in stderr.lower():
                    return {"success": False, "applied": False, "error": f"Git status failed for {p_str}: {stderr[:300]}", "path": p_str}
            resolved_files[p_str] = p_candidate

        # 2. Read and backup all target files in memory
        backups: dict[Path, str] = {}
        file_contents: dict[Path, str] = {}
        for rel_path, fpath in resolved_files.items():
            if fpath not in backups:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                backups[fpath] = content
                file_contents[fpath] = content

        # 3. Apply edits in-memory and verify uniqueness
        for idx, edit in enumerate(edits):
            p_str = edit.get("path") or edit.get("file")
            old_str = edit.get("old") or edit.get("target") or edit.get("target_content")
            new_str = edit.get("new") if "new" in edit else (edit.get("replacement") or edit.get("replacement_content"))
            fpath = resolved_files[p_str]
            current_text = file_contents[fpath]

            expected_sha = edit.get("expected_sha256") or edit.get("expected_sha")
            if expected_sha:
                cur_sha = hashlib.sha256(current_text.encode("utf-8")).hexdigest()
                if cur_sha.lower() != str(expected_sha).lower():
                    return {
                        "success": False,
                        "applied": False,
                        "error": f"CAS conflict for {p_str}: expected sha256 {str(expected_sha)[:12]}, file has {cur_sha[:12]}",
                        "conflict": True,
                        "current_sha256": cur_sha,
                        "path": p_str,
                    }

            count = current_text.count(old_str)
            if count == 0:
                return {
                    "success": False,
                    "applied": False,
                    "error": f"edit #{idx}: target text not found in {p_str}",
                    "path": p_str,
                }
            if count > 1:
                return {
                    "success": False,
                    "applied": False,
                    "error": f"edit #{idx}: target text found multiple times ({count}) in {p_str}. Must be unique.",
                    "path": p_str,
                }
            hunks = dirty_hunks.get(fpath)
            if hunks is not None:
                first_line = current_text.count("\n", 0, current_text.find(old_str)) + 1
                end_offset = current_text.find(old_str) + len(old_str)
                last_line = first_line + current_text.count("\n", current_text.find(old_str), end_offset)
                if any(first_line <= dirty_end and last_line >= dirty_start for dirty_start, dirty_end in hunks):
                    if not covered_by_verified_lease(fpath):
                        return {
                            "success": False,
                            "applied": False,
                            "error": f"refusing replacement overlapping unowned dirty hunk: {p_str}",
                            "path": p_str,
                        }
            file_contents[fpath] = current_text.replace(old_str, new_str, 1)

        # 4. Syntax preflight on modified Python files
        for fpath, new_text in file_contents.items():
            if fpath.suffix == ".py":
                try:
                    compile(new_text, str(fpath), "exec")
                except SyntaxError as syn_err:
                    rel = str(fpath.relative_to(p_root)).replace("\\", "/")
                    return {
                        "success": False,
                        "applied": False,
                        "error": f"Syntax error in {rel} after replacement: {syn_err.msg}",
                        "path": rel,
                    }

        if dry_run:
            return {
                "success": True,
                "applied": False,
                "dry_run": True,
                "edits_count": len(edits),
                "modified_files": [str(p.relative_to(p_root)).replace("\\", "/") for p in file_contents],
            }

        # 5. Commit writes atomically
        written_files: list[Path] = []
        try:
            for fpath, new_text in file_contents.items():
                fpath.write_text(new_text, encoding="utf-8")
                written_files.append(fpath)
        except Exception as exc:
            for written in written_files:
                written.write_text(backups[written], encoding="utf-8")
            return {"success": False, "applied": False, "error": f"Failed during disk write, rolled back: {exc}"}

        new_hashes = {
            str(p.relative_to(p_root)).replace("\\", "/"): hashlib.sha256(txt.encode("utf-8")).hexdigest()
            for p, txt in file_contents.items()
        }
        return {
            "success": True,
            "applied": True,
            "edits_count": len(edits),
            "modified_files": [str(p.relative_to(p_root)).replace("\\", "/") for p in file_contents],
            "sha256": new_hashes,
        }

