from __future__ import annotations

import keyword
import os
from pathlib import Path
import re
import stat
import time
from typing import Any

from .deterministic_test_paths import (
    build_test_file_result,
    build_test_matrix_response,
    collect_test_matrix_rows,
    extract_test_case_names,
    is_test_matrix_source,
    run_test_matrix_workers,
    select_test_matrix_targets,
)
from .process_utils import canonical_root
from .reparse_points import _is_symlink_or_reparse_point
from .repo_topology import repo_topology as _repo_topology
from .test_framework_selection import detect_test_framework
from .test_matrix_commands import build_test_file_command
from .topology_labels import classify_topology_layer
from .topology_summary import build_topology_summary_markdown


class DeterministicTestMixin:
    def cross_repo_contract(
        self,
        backend_root: str,
        frontend_root: str,
    ) -> dict[str, Any]:
        """Validate API contract alignment between backend routes and frontend API callers."""
        b_root = canonical_root(backend_root)
        f_root = canonical_root(frontend_root)

        backend_spec = self.extract_api_spec(b_root)
        backend_endpoints = backend_spec.get("endpoints", [])
        backend_routes: dict[tuple[str, str], dict[str, Any]] = {}
        for ep in backend_endpoints:
            m = str(ep.get("method", "GET")).upper()
            p = str(ep.get("path", "")).strip()
            norm_p = re.sub(r"\{[a-zA-Z0-9_]+\}", ":param", p)
            norm_p = re.sub(r"<[a-zA-Z0-9_:]+>", ":param", norm_p)
            backend_routes[(m, norm_p)] = ep

        frontend_calls: list[dict[str, Any]] = []
        f_path = Path(f_root)
        if f_path.is_dir():
            for p in f_path.rglob("*"):
                if p.suffix in (".ts", ".tsx", ".js", ".jsx", ".vue", ".svelte", ".py") and not any(d in p.parts for d in ("node_modules", ".git", "dist", "build")):
                    try:
                        content = p.read_text(encoding="utf-8", errors="replace")
                        rel = str(p.relative_to(f_path)).replace("\\", "/")
                        for line_no, line in enumerate(content.splitlines(), 1):
                            m_call = re.findall(r"(?:fetch|axios\.(get|post|put|delete|patch)|apiFetch|get|post)\s*\(\s*['\"`](/api/[^'\"`]+)['\"`]", line)
                            for item in m_call:
                                if isinstance(item, tuple):
                                    http_m = (item[0] or "GET").upper()
                                    path_c = item[1]
                                else:
                                    http_m = "GET"
                                    path_c = item
                                norm_c = re.sub(r"/\$\{[^}]+\}", "/:param", path_c)
                                norm_c = re.sub(r"/[0-9]+", "/:param", norm_c)
                                frontend_calls.append({
                                    "method": http_m,
                                    "path": path_c,
                                    "normalized_path": norm_c,
                                    "file": rel,
                                    "line": line_no,
                                })
                    except Exception:
                        pass

        matched_routes: list[dict[str, Any]] = []
        missing_backend_routes: list[dict[str, Any]] = []
        for call in frontend_calls:
            k = (call["method"], call["normalized_path"])
            found = backend_routes.get(k)
            if not found:
                alt_methods = [b_ep for (b_m, b_p), b_ep in backend_routes.items() if b_p == call["normalized_path"]]
                if alt_methods:
                    missing_backend_routes.append({**call, "issue": f"Method mismatch: frontend uses {call['method']} but backend expects {alt_methods[0].get('method')}"})
                else:
                    missing_backend_routes.append({**call, "issue": "Endpoint not defined on backend"})
            else:
                matched_routes.append({**call, "backend_handler": found.get("handler")})

        unused_backend: list[dict[str, Any]] = []
        f_norm_paths = {c["normalized_path"] for c in frontend_calls}
        for (b_m, b_p), ep in backend_routes.items():
            if b_p not in f_norm_paths:
                unused_backend.append(ep)

        return {
            "success": True,
            "backend_root": b_root,
            "frontend_root": f_root,
            "backend_endpoints_count": len(backend_routes),
            "frontend_calls_count": len(frontend_calls),
            "matched_contracts_count": len(matched_routes),
            "violations_count": len(missing_backend_routes),
            "violations": missing_backend_routes,
            "unmatched_frontend_calls": [v["path"] for v in missing_backend_routes],
            "matched": matched_routes,
            "matched_endpoints": [m["path"] for m in matched_routes],
            "unused_backend_endpoints": unused_backend,
            "uncalled_backend_endpoints": [u.get("path") for u in unused_backend],
        }

    def synthesize_commit(
        self,
        root: str,
        message_hint: str = "",
        *,
        task_id: str = "",
        tasks: list[dict[str, Any]] | None = None,
        receipts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Analyze local git diff and synthesize a clean Conventional Commit message."""
        import subprocess
        import shutil
        from .process_utils import hidden_run_kwargs

        task_list = list(tasks or [])
        receipt_list = list(receipts or [])
        primary_goal = ""
        for t in task_list:
            g = str(t.get("goal") or (t.get("contract", {}) if isinstance(t.get("contract"), dict) else {}).get("goal", "")).strip()
            if g:
                primary_goal = g
                break

        effective_hint = message_hint or primary_goal

        def _format_body_sections(file_lines: list[str]) -> tuple[str, str]:
            sections: list[str] = []
            if file_lines:
                sections.append("\n".join(file_lines))
            if task_list:
                t_lines = ["Tasks:"]
                for t in task_list[:5]:
                    tid = t.get("task_id", "")
                    g = str(t.get("goal") or (t.get("contract", {}) if isinstance(t.get("contract"), dict) else {}).get("goal", "")).strip()
                    if tid and g:
                        t_lines.append(f"- [{tid}]: {g}")
                    elif g:
                        t_lines.append(f"- {g}")
                if len(t_lines) > 1:
                    sections.append("\n".join(t_lines))
            if receipt_list:
                r_lines = ["Verified Criteria:"]
                for r in receipt_list[:10]:
                    crit = r.get("criterion", "")
                    ev_id = r.get("evidence_id", "")
                    suffix = f" (evidence: {ev_id})" if ev_id else ""
                    r_lines.append(f"- [x] {crit}{suffix}")
                if len(r_lines) > 1:
                    sections.append("\n".join(r_lines))
            body_text = "\n\n".join(sections)
            return body_text, sections[0] if sections else ""

        st = self.git_status(root)
        if not st.get("is_git"):
            header = f"feat(core): {effective_hint or 'update repository files'}"
            body_text, _ = _format_body_sections(["- modified repository files"])
            return {
                "success": True,
                "branch": "main (non-git)",
                "primary_scope": "core",
                "type": "feat",
                "header": header,
                "body": body_text,
                "commit_message": f"{header}\n\n{body_text}",
                "stat_summary": "Non-git directory",
                "tasks": task_list,
                "receipts": receipt_list,
            }

        resolved = self._root(root)
        git_exe = shutil.which("git") or "git"
        try:
            diff_res = subprocess.run(
                [git_exe, "-C", resolved, "diff", "HEAD", "--stat"],
                capture_output=True, text=True, timeout=3.0, check=False,
                encoding="utf-8", errors="replace",
                **hidden_run_kwargs(),
            )
            stat_summary = diff_res.stdout.strip()
        except Exception:
            stat_summary = ""

        mod_files = st.get("modified", []) + st.get("staged", [])
        if not mod_files:
            return {"success": True, "commit_message": "chore: no modified files detected", "summary": "Working tree clean"}

        # Determine primary scope
        scopes = []
        for f in mod_files:
            parts = f.replace("\\", "/").split("/")
            if len(parts) > 1:
                scopes.append(parts[0] if parts[0] not in ("src", "lib") else parts[1] if len(parts) > 2 else parts[0])
            else:
                scopes.append(parts[0])
        primary_scope = max(set(scopes), key=scopes.count) if scopes else "core"

        # Determine conventional type
        any_test = any("test" in f.lower() for f in mod_files)
        any_doc = any(f.endswith(".md") or "doc" in f.lower() for f in mod_files)
        any_src = any(f.endswith((".py", ".cs", ".ts", ".js", ".go", ".rs")) for f in mod_files)

        c_type = "feat" if any_src else "test" if any_test else "docs" if any_doc else "refactor"
        if effective_hint:
            header = f"{c_type}({primary_scope}): {effective_hint}"
        else:
            header = f"{c_type}({primary_scope}): update {len(mod_files)} component(s)"

        body_lines = [f"- update `{f}`" for f in mod_files[:10]]
        if len(mod_files) > 10:
            body_lines.append(f"- and {len(mod_files) - 10} other file(s)")

        body_text, _ = _format_body_sections(body_lines)
        full_message = f"{header}\n\n{body_text}"
        return {
            "success": True,
            "branch": st.get("branch"),
            "primary_scope": primary_scope,
            "type": c_type,
            "header": header,
            "body": body_text,
            "commit_message": full_message,
            "stat_summary": stat_summary,
            "tasks": task_list,
            "receipts": receipt_list,
        }

    @staticmethod
    def _detect_test_framework(resolved_root: Path) -> tuple[str, str, bool, list[str]]:
        return detect_test_framework(resolved_root)

    def test_matrix(self, root: str) -> dict[str, Any]:
        """Discover test frameworks, test files, and test mappings in the repository."""
        resolved_root = Path(self._root(root))
        root_str = str(resolved_root)
        test_files: list[dict[str, Any]] = []
        framework, run_all_cmd, incomplete, warnings = self._detect_test_framework(resolved_root)

        # Only current filesystem entries can back a matrix row. Keep directory
        # enumeration bounded; the durable index is deliberately not a source
        # of truth for test targets because it can lag deletions and renames.
        max_depth = 25
        max_files = 2000
        max_targets = 40
        max_file_bytes = min(int(getattr(self.repo_tools, "max_file_bytes", 1_000_000)), 256_000)
        max_total_bytes = 2_000_000
        deadline = time.monotonic() + 5.0
        target_paths: list[tuple[str, Path, os.stat_result]] = []
        enumerated = 0
        inventory_status: dict[str, Any] = {
            "complete": True, "reasons": [], "examples": {},
            "examples_truncated": False, "excluded_link_paths": 0,
        }
        try:
            for candidate, snapshot_stat in self.repo_tools._iter_files_with_stat(
                root_str, max_depth=max_depth, max_files=max_files,
                inventory_status=inventory_status, inventory_deadline=deadline,
            ):
                if time.monotonic() >= deadline:
                    incomplete = True
                    warnings.append("test_file_enumeration_deadline_exceeded")
                    break
                enumerated += 1
                try:
                    rel = candidate.relative_to(resolved_root).as_posix()
                    if not is_test_matrix_source(rel):
                        continue
                    lst = candidate.lstat()
                    if stat.S_ISLNK(lst.st_mode) or (getattr(lst, "st_file_attributes", 0) & 0x400):
                        incomplete = True
                        warnings.append("test_file_reparse_point_skipped")
                        continue
                    current_stat = candidate.stat()
                    candidate.resolve(strict=True).relative_to(resolved_root)
                    if not stat.S_ISREG(current_stat.st_mode) or current_stat.st_size > max_file_bytes:
                        incomplete = True
                        warnings.append("test_file_invalid_or_too_large_skipped")
                        continue
                    if (current_stat.st_dev, current_stat.st_ino, current_stat.st_size, current_stat.st_mtime_ns) != (
                        snapshot_stat.st_dev, snapshot_stat.st_ino, snapshot_stat.st_size, snapshot_stat.st_mtime_ns,
                    ):
                        incomplete = True
                        warnings.append("test_file_changed_during_enumeration")
                        continue
                    target_paths.append((rel, candidate, current_stat))
                except (OSError, ValueError):
                    incomplete = True
                    warnings.append("test_file_unavailable_or_outside_root")
            if time.monotonic() >= deadline and "test_file_enumeration_deadline_exceeded" not in warnings:
                incomplete = True
                warnings.append("test_file_enumeration_deadline_exceeded")
            inventory_reasons = inventory_status.get("reasons", [])
            if not inventory_status.get("complete", True):
                incomplete = True
                if not inventory_reasons:
                    warnings.append("test_file_inventory_incomplete")
            for reason in inventory_reasons:
                incomplete = True
                if reason == "time_limit":
                    warning = "test_file_enumeration_deadline_exceeded"
                elif reason == "file_limit":
                    warning = "test_file_enumeration_limit_reached"
                else:
                    warning = f"test_file_inventory_{reason}"
                warnings.append(warning)
            if enumerated >= max_files:
                incomplete = True
                warnings.append("test_file_enumeration_limit_reached")
        except Exception:
            incomplete = True
            warnings.append("test_file_enumeration_failed")

        selected, selection_incomplete, selection_warnings = select_test_matrix_targets(
            target_paths,
            max_targets=max_targets,
            max_total_bytes=max_total_bytes,
        )
        incomplete = incomplete or selection_incomplete
        warnings.extend(selection_warnings)

        def _extract_file_info(item: tuple[str, Path, os.stat_result]) -> dict[str, Any] | None:
            rel, f, before = item
            suffix = f.suffix.lower()
            try:
                if time.monotonic() >= deadline:
                    raise TimeoutError("test matrix read deadline exceeded")
                # Match the read ceiling to the prevalidated size. The snapshot
                # helper reads max_bytes + 1 for growth detection, so aggregate
                # selection reserves that lookahead byte before dispatch.
                digest, lines = self.repo_tools._read_snapshot(f, stat=before, max_bytes=int(before.st_size))
                txt = "\n".join(lines)
                lstat_after = f.lstat()
                after = f.stat()
                if stat.S_ISLNK(lstat_after.st_mode) or (getattr(lstat_after, "st_file_attributes", 0) & 0x400):
                    raise OSError("file became a reparse point during bounded read")
                f.resolve(strict=True).relative_to(resolved_root)
                if not stat.S_ISREG(after.st_mode) or (
                    before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                    raise OSError("file changed during bounded read")
                cases, cases_scan_complete = extract_test_case_names(
                    txt, suffix, should_continue=lambda: time.monotonic() < deadline,
                )
            except Exception as exc:
                return {"_omitted": type(exc).__name__}

            # Keep arguments structured. Display strings include only simple
            # shell tokens; paths needing quoting remain available as argv.
            run_argv, run_file_cmd = build_test_file_command(f, rel, framework)
            return build_test_file_result(
                rel, digest, cases, cases_scan_complete, suffix,
                run_argv, run_file_cmd,
            )

        if selected:
            worker_rows = run_test_matrix_workers(_extract_file_info, selected)
            rows, rows_incomplete, row_warnings = collect_test_matrix_rows(worker_rows)
            test_files.extend(rows)
            incomplete = incomplete or rows_incomplete
            warnings.extend(row_warnings)

        return build_test_matrix_response(
            framework,
            run_all_cmd,
            test_files,
            incomplete,
            warnings,
            max_depth=max_depth,
            max_files=max_files,
        )

    def affected_tests(self, root: str, changed_paths: list[str] | None = None, base: str = "HEAD") -> dict[str, Any]:
        """Map changed paths/symbols directly to affected test files and formulate targeted command."""
        resolved_root = Path(self._root(root))
        if changed_paths is None:
            changed_paths = []
            import subprocess
            try:
                from .process_utils import hidden_run_kwargs
                p = subprocess.run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", "."], cwd=str(resolved_root), capture_output=True, timeout=5, **hidden_run_kwargs())
                if p.returncode != 0:
                    return {"success": False, "error": "Unable to determine changed paths from git status",
                            "error_code": "git_status_failed", "exit_code": p.returncode,
                            "terminal": True, "retryable": False}
                if not isinstance(p.stdout, bytes):
                    return {"success": False, "error": "Git status returned malformed path records",
                            "error_code": "git_status_malformed", "terminal": True, "retryable": False}
                from .git_status_paths import parse_porcelain_status_paths
                parsed_paths = parse_porcelain_status_paths(p.stdout)
                if parsed_paths is None:
                    return {"success": False, "error": "Git status returned malformed path records",
                            "error_code": "git_status_malformed", "terminal": True, "retryable": False}
                changed_paths.extend(parsed_paths)
                if changed_paths:
                    prefix_result = subprocess.run(["git", "rev-parse", "--show-prefix"], cwd=str(resolved_root), capture_output=True, timeout=5, **hidden_run_kwargs())
                    if (prefix_result.returncode != 0 or not isinstance(prefix_result.stdout, bytes)
                            or not prefix_result.stdout.endswith(b"\n")):
                        return {"success": False, "error": "Unable to determine repository path prefix",
                                "error_code": "git_prefix_failed", "terminal": True, "retryable": False}
                    prefix = os.fsdecode(prefix_result.stdout[:-1])
                    if prefix and not prefix.endswith("/"):
                        return {"success": False, "error": "Git returned malformed path prefix",
                                "error_code": "git_prefix_failed", "terminal": True, "retryable": False}
                    if prefix:
                        changed_paths = [path[len(prefix):] for path in changed_paths if path.startswith(prefix)]
            except subprocess.TimeoutExpired:
                return {"success": False, "error": "Git status timed out while determining changed paths",
                        "error_code": "git_status_timeout", "timed_out": True,
                        "terminal": False, "retryable": True}
            except Exception as exc:
                return {"success": False, "error": "Git status unavailable while determining changed paths",
                        "error_code": "git_status_unavailable", "error_type": type(exc).__name__,
                        "terminal": True, "retryable": False}

        def normalize_changed_path(value: str) -> str:
            normalized = value.replace("\\", "/")
            while normalized.startswith("./"):
                normalized = normalized[2:]
            return normalized

        norm_changed = [normalize_changed_path(p) for p in changed_paths if p]
        if not norm_changed:
            framework, _, _, _ = self._detect_test_framework(resolved_root)
            return {
                "success": True,
                "framework": framework,
                "changed_files": [],
                "test_files": [],
                "suggested_command": "",
                "confidence": 1.0,
            }

        matrix = self.test_matrix(root)
        framework = matrix.get("framework", "unknown")
        all_tests = matrix.get("test_files", [])

        test_paths_set: set[str] = set()
        graph_complete = False
        for t_linked in self.get_test_source_links(str(resolved_root), norm_changed):
            test_paths_set.add(t_linked)
        for p in norm_changed:
            p_lower = p.lower()
            if "test" in p_lower or "spec" in p_lower:
                test_paths_set.add(p)

        stems = {Path(p).stem.lower().replace("test_", "").replace("_test", "").replace(".test", "").replace(".spec", "") for p in norm_changed}
        for t in all_tests:
            t_path = t["path"].replace("\\", "/")
            t_stem = Path(t_path).stem.lower().replace("test_", "").replace("_test", "").replace(".test", "").replace(".spec", "")
            for s in stems:
                if s and (s == t_stem or s in t_stem or t_stem in s):
                    test_paths_set.add(t_path)

        code_index = self.code_index
        if code_index is None:
            # Direct DeterministicEngine callers may not receive the shared index
            # that services inject. Open the existing index lazily; preprocessing
            # owns demand-based admission and this query must not index the project.
            try:
                from .code_index import CodeIndex

                candidate_index = CodeIndex(self.config, self.repo_tools)
                self.code_index = candidate_index
                code_index = candidate_index
            except Exception:
                code_index = None
        if code_index is not None:
            try:
                imp = code_index.impact(str(resolved_root), norm_changed)
                if not isinstance(imp, dict) or not isinstance(imp.get("suggested_tests", []), list):
                    raise ValueError("code index returned malformed impact data")
                suggested_tests = imp.get("suggested_tests", [])
                if any(not isinstance(st, dict) or not isinstance(st.get("path"), str) for st in suggested_tests):
                    raise ValueError("code index returned malformed test paths")
                # Preserve conservative completeness until dependency coverage is verified.
                graph_complete = imp.get("success") is True and imp.get("graph_complete") is True
                for st in suggested_tests:
                    test_paths_set.add(st["path"].replace("\\", "/"))
            except Exception:
                graph_complete = False

        from .test_selection import affected_test_command, compatible_tests
        matched_tests, incompatible_tests = compatible_tests(sorted(test_paths_set), framework)
        cmd = affected_test_command(matched_tests, framework)

        return {
            "success": True,
            "framework": framework,
            "changed_files": norm_changed,
            "test_files": matched_tests,
            "excluded_incompatible_tests": incompatible_tests,
            "requires_multiple_runners": bool(incompatible_tests),
            "suggested_command": cmd,
            "confidence": 0.95 if matched_tests and graph_complete and not incompatible_tests else 0.5,
            "selection_complete": graph_complete and not incompatible_tests,
        }

    def repo_topology(self, root: str) -> dict[str, Any]:
        """Return a bounded local Python import graph and heuristic path labels."""
        return _repo_topology(
            root,
            root_resolver=self._root,
            repo_tools=self.repo_tools,
            is_symlink_or_reparse_point=_is_symlink_or_reparse_point,
            classify_layer=classify_topology_layer,
            build_summary=build_topology_summary_markdown,
        )

    def ast_rename(self, root: str, target_file: str, old_symbol: str, new_symbol: str, apply_changes: bool = False) -> dict[str, Any]:
        """Mechanically rename a symbol across the target file and its callers using AST / pattern replacement."""
        if not old_symbol or not new_symbol or old_symbol == new_symbol:
            return {"success": False, "error": "Invalid old or new symbol"}
        
        resolved_root = Path(self._root(root))
        affected_files: set[str] = set()
        if target_file and target_file not in (".", "*", "repo", "all"):
            norm_target = target_file.replace("\\", "/").lstrip("./")
            target_path = resolved_root / norm_target
            if not target_path.is_file():
                return {"success": False, "error": f"Target file not found: {norm_target}"}
            affected_files.add(norm_target)

        code_exts = {".py", ".ts", ".tsx", ".js", ".jsx", ".cs", ".go", ".rs", ".java", ".cpp", ".c", ".h", ".hpp", ".rb", ".php"}
        all_code_files = [
            str(p.relative_to(resolved_root)).replace("\\", "/")
            for p in self.repo_tools.iter_files(str(resolved_root))
            if p.suffix.lower() in code_exts
        ]
        sym_pattern = re.compile(rf"\b{re.escape(old_symbol)}\b")
        
        for rel in all_code_files:
            fpath = resolved_root / rel
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                if sym_pattern.search(content):
                    affected_files.add(rel)
            except Exception:
                pass

        diffs: dict[str, str] = {}
        modified_contents: dict[str, str] = {}

        for rel in affected_files:
            fpath = resolved_root / rel
            try:
                old_txt = fpath.read_text(encoding="utf-8", errors="replace")
                new_txt = sym_pattern.sub(new_symbol, old_txt)
                if new_txt != old_txt:
                    modified_contents[rel] = new_txt
                    import difflib
                    diff_lines = list(difflib.unified_diff(
                        old_txt.splitlines(keepends=True),
                        new_txt.splitlines(keepends=True),
                        fromfile=rel,
                        tofile=rel,
                    ))
                    diffs[rel] = "".join(diff_lines)
            except Exception as e:
                return {"success": False, "error": f"Error processing {rel}: {e}"}

        if apply_changes:
            originals = {rel: (resolved_root / rel).read_text(encoding="utf-8", errors="replace") for rel in modified_contents}
            for rel, new_txt in modified_contents.items():
                (resolved_root / rel).write_text(new_txt, encoding="utf-8")

            import py_compile
            for rel in modified_contents:
                if rel.endswith(".py"):
                    try:
                        py_compile.compile(str(resolved_root / rel), doraise=True)
                    except py_compile.PyCompileError as syn_err:
                        for r_rel, orig_txt in originals.items():
                            (resolved_root / r_rel).write_text(orig_txt, encoding="utf-8")
                        return {
                            "success": False,
                            "applied": False,
                            "rolled_back": True,
                            "error": f"Syntax error in {rel} after rename: {syn_err.msg}",
                        }

        return {
            "success": True,
            "old_symbol": old_symbol,
            "new_symbol": new_symbol,
            "applied": apply_changes,
            "affected_files": sorted(modified_contents.keys()),
            "diffs": diffs,
        }

    def generate_mocks(self, root: str, target_file: str, symbol: str) -> dict[str, Any]:
        """Generate mock/stub objects and test fixtures for a target class, interface, or function."""
        if not symbol:
            return {"success": False, "error": "Symbol must not be empty"}

        resolved_root = Path(self._root(root))
        norm_target = target_file.replace("\\", "/").lstrip("./")
        target_path = resolved_root / norm_target
        if not target_path.is_file():
            return {"success": False, "error": f"Target file not found: {norm_target}"}

        try:
            content = target_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"success": False, "error": f"Failed to read target file: {e}"}

        ext = target_path.suffix.lower()
        if ext == ".py" and (not symbol.isidentifier() or keyword.iskeyword(symbol)):
            return {
                "success": False,
                "error": "Python mock symbols must be valid identifiers",
            }
        if ext == ".py":
            import ast
            try:
                tree = ast.parse(content, filename=norm_target)
            except Exception:
                tree = None

            found_node = None
            if tree:
                for node in ast.walk(tree):
                    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol:
                        found_node = node
                        break

            if found_node and isinstance(found_node, ast.ClassDef):
                methods = [
                    m.name for m in found_node.body
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and not m.name.startswith("__")
                ]
                mock_lines = [
                    f"class Mock{symbol}:",
                    f'    """Mock implementation of {symbol}."""',
                    "    def __init__(self, **kwargs):",
                    "        for k, v in kwargs.items():",
                    "            setattr(self, k, v)",
                ]
                for m in methods:
                    mock_lines.append(f"    def {m}(self, *args, **kwargs):")
                    mock_lines.append(f"        return MagicMock(name='{symbol}.{m}')")
                if not methods:
                    mock_lines.append("    pass")

                fixture_lines = [
                    "@pytest.fixture",
                    f"def mock_{symbol.lower()}():",
                    f"    return Mock{symbol}()",
                    "",
                    "@pytest.fixture",
                    f"def autospec_{symbol.lower()}():",
                    f"    return unittest.mock.create_autospec({symbol}, instance=True)",
                ]
                return {
                    "success": True,
                    "file": norm_target,
                    "symbol": symbol,
                    "kind": "class",
                    "language": "python",
                    "methods": methods,
                    "mock_code": "\n".join(mock_lines),
                    "fixture_code": "\n".join(fixture_lines),
                }
            elif found_node and isinstance(found_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                module_name = norm_target.rsplit(".", 1)[0].replace("/", ".")
                if module_name.endswith(".__init__"):
                    module_name = module_name[:-len(".__init__")]
                fixture_lines = [
                    "@pytest.fixture",
                    f"def mock_{symbol}():",
                    f"    with unittest.mock.patch('{module_name}.{symbol}') as m:",
                    "        yield m",
                ]
                return {
                    "success": True,
                    "file": norm_target,
                    "symbol": symbol,
                    "kind": "function",
                    "language": "python",
                    "mock_code": f"mock_{symbol} = unittest.mock.MagicMock(name='{symbol}')",
                    "fixture_code": "\n".join(fixture_lines),
                }
            else:
                mock_code = f"mock_{symbol} = unittest.mock.MagicMock(name='{symbol}')"
                fixture_code = (
                    "@pytest.fixture\n"
                    f"def mock_{symbol.lower()}():\n"
                    f"    return unittest.mock.MagicMock(name={symbol!r})"
                )
                return {
                    "success": True,
                    "file": norm_target,
                    "symbol": symbol,
                    "kind": "generic",
                    "language": "python",
                    "mock_code": mock_code,
                    "fixture_code": fixture_code,
                }
        elif ext in {".ts", ".tsx", ".js", ".jsx"}:
            mock_code = f"export const mock{symbol} = {{\n  // stub methods for {symbol}\n}};"
            fixture_code = f"jest.mock('./{target_path.stem}', () => ({{\n  {symbol}: jest.fn().mockImplementation(() => mock{symbol}),\n}}));"
            return {
                "success": True,
                "file": norm_target,
                "symbol": symbol,
                "kind": "generic",
                "language": "typescript" if ext in {".ts", ".tsx"} else "javascript",
                "mock_code": mock_code,
                "fixture_code": fixture_code,
            }
        else:
            return {
                "success": True,
                "file": norm_target,
                "symbol": symbol,
                "kind": "generic",
                "language": ext.lstrip("."),
                "mock_code": f"// Mock implementation for {symbol}",
                "fixture_code": f"// Test fixture for {symbol}",
            }

