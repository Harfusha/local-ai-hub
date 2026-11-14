from __future__ import annotations

import ast as _ast
import os as _os
import time as _time
from pathlib import Path, Path as _Path
from typing import Any


def run_security_audit(
    engine: Any,
    root: str,
    limit: int,
    *,
    secret_patterns: Any,
    code_smell_patterns: Any,
    python_shell_injection_lines: Any,
    yaml_load_match_lines: Any,
    pattern_match_lines: Any,
    path_type: Any = _Path,
    ast_module: Any = _ast,
    os_module: Any = _os,
    time_module: Any = _time,
) -> dict[str, Any]:
    resolved_root = path_type(engine._root(root))

    findings: list[dict[str, Any]] = []
    deadline = time_module.monotonic() + 30.0
    raw_files, inventory = engine.repo_tools.security_inventory(str(resolved_root), deadline=deadline)
    def _sec_priority(p: Path) -> int:
        try:
            parts = p.relative_to(resolved_root).parts
        except ValueError:
            return 2
        if not parts or len(parts) == 1:
            return 0
        top = parts[0].lower()
        if top in {"src", "lib", "app", "core", "server", "api"}:
            return 0
        if top in {"tools", "scripts", "bin"}:
            return 1
        if top in {"tests", "test", "fixtures"}:
            return 3
        return 2
    candidate_files = sorted(raw_files, key=_sec_priority)
    scanned_files = 0
    eligible_files = 0
    skipped_files = 0
    scan_complete = inventory.get("complete") is True
    limit_reached = False
    scanned_bytes = 0
    scan_errors: list[dict[str, str]] = []
    max_file_bytes = min(2_000_000, max(1, int(getattr(engine.repo_tools, "max_file_bytes", 2_000_000))))
    stop_reason = "" if scan_complete else "inventory_incomplete"


    for f in candidate_files:
        if len(findings) >= limit:
            limit_reached = True
            scan_complete = False
            stop_reason = "findings_limit"
            break
        if time_module.monotonic() >= deadline or scanned_bytes >= 32 * 1024 * 1024:
            scan_complete = False
            stop_reason = "time_or_byte_budget"
            break
        if f.suffix.lower() not in {".py", ".ts", ".js", ".cs", ".go", ".rs", ".json", ".toml", ".yaml", ".yml", ".env"}:
            skipped_files += 1
            continue
        eligible_files += 1
        rel = str(f.relative_to(resolved_root)).replace("\\", "/")
        try:
            target = f.resolve(strict=True)
            target.relative_to(resolved_root)
            import stat
            flags = os_module.O_RDONLY | getattr(os_module, "O_BINARY", 0) | getattr(os_module, "O_NOFOLLOW", 0) | getattr(os_module, "O_NONBLOCK", 0)
            descriptor = os_module.open(target, flags)
            try:
                opened = os_module.fstat(descriptor)
                if not stat.S_ISREG(opened.st_mode):
                    raise ValueError("security source is not a regular file")
                source = os_module.fdopen(descriptor, "rb")
                descriptor = -1
                with source:
                    remaining_bytes = 32 * 1024 * 1024 - scanned_bytes
                    read_bound = min(max_file_bytes, remaining_bytes)
                    raw = source.read(read_bound + 1)
                    after_read = os_module.fstat(source.fileno())
                target.resolve(strict=True).relative_to(resolved_root)
                current = target.stat()
                opened_state = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
                after_state = (after_read.st_dev, after_read.st_ino, after_read.st_size, after_read.st_mtime_ns, after_read.st_ctime_ns)
                if opened_state != after_state or (opened.st_dev, opened.st_ino, opened.st_size) != (current.st_dev, current.st_ino, current.st_size):
                    raise ValueError("security source changed during read")
            finally:
                if descriptor >= 0:
                    os_module.close(descriptor)
            scanned_bytes += len(raw)
            if len(raw) > read_bound:
                raise ValueError("security source exceeds file or aggregate byte bound")
            txt = raw.decode("utf-8", errors="replace")
            lines = txt.splitlines()
            scanned_files += 1
            for i, line in enumerate(lines, 1):
                if len(findings) >= limit or (i % 1024 == 0 and time_module.monotonic() >= deadline):
                    scan_complete = False
                    limit_reached = len(findings) >= limit
                    stop_reason = "findings_limit" if limit_reached else "time_budget"
                    break
                stripped = line.strip()
                if stripped.startswith(("#", "//", "/*", "*")):
                    continue

                for name, pat in secret_patterns:
                    if pat.search(line):
                        findings.append({
                            "severity": "HIGH",
                            "type": "secret_leak",
                            "title": name,
                            "path": rel,
                            "line": i,
                            "snippet": "[credential-like value omitted]",
                        })
                        break

            python_tree: ast_module.AST | None = None
            if rel.lower().endswith(".py") and len(findings) < limit and time_module.monotonic() < deadline:
                try:
                    python_tree = ast_module.parse(txt)
                except (SyntaxError, ValueError):
                    scan_complete = False
                    if len(scan_errors) < 20:
                        scan_errors.append({"path": rel, "error_type": "ASTParseError"})

            for name, pat in code_smell_patterns:
                if len(findings) >= limit or time_module.monotonic() >= deadline:
                    scan_complete = False
                    limit_reached = len(findings) >= limit
                    stop_reason = "findings_limit" if limit_reached else "time_budget"
                    break
                if name == "Shell Injection Risk":
                    if not rel.lower().endswith(".py"):
                        continue
                    line_numbers = (
                        python_shell_injection_lines(txt, tree=python_tree)
                        if python_tree is not None else []
                    )
                elif name == "Unsafe eval/exec" and rel.lower().endswith(".py"):
                    if python_tree is None:
                        line_numbers = []
                    else:
                        line_numbers = sorted(
                            {
                                node.lineno
                                for node in ast_module.walk(python_tree)
                                if isinstance(node, ast_module.Call)
                                and (
                                    isinstance(node.func, ast_module.Name)
                                    and node.func.id in {"eval", "exec"}
                                    or isinstance(node.func, ast_module.Attribute)
                                    and node.func.attr in {"eval", "exec"}
                                    and isinstance(node.func.value, ast_module.Name)
                                    and node.func.value.id in {"builtins", "__builtins__"}
                                )
                            }
                        )
                elif name == "Unsafe PyYAML":
                    line_numbers = yaml_load_match_lines(txt)
                else:
                    line_numbers = pattern_match_lines(txt, pat)
                for line_no in line_numbers:
                    matched_line = lines[line_no - 1].strip() if line_no <= len(lines) else ""
                    if matched_line.startswith(("#", "//", "/*", "*")):
                        continue
                    if not any(fd["path"] == rel and fd["line"] == line_no and fd["title"] == name for fd in findings):
                        findings.append({
                            "severity": "MEDIUM",
                            "type": "code_vulnerability",
                            "title": name,
                            "path": rel,
                            "line": line_no,
                            "snippet": matched_line[:120] or pat.pattern[:120],
                        })
                    if len(findings) >= limit:
                        limit_reached = True
                        scan_complete = False
                        stop_reason = "findings_limit"
                        break
        except Exception as exc:
            scan_complete = False
            skipped_files += 1
            if len(scan_errors) < 20:
                scan_errors.append({
                    "path": rel,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:200],
                })


    if not scan_complete and not stop_reason and scan_errors:
        stop_reason = "scan_errors"
    if scan_complete:
        _final_files, final_inventory = engine.repo_tools.security_inventory(str(resolved_root), deadline=deadline)
        initial_identity = inventory.get("_identity")
        final_identity = final_inventory.get("_identity")
        if (final_inventory.get("complete") is not True or not isinstance(initial_identity, dict)
                or not isinstance(final_identity, dict) or initial_identity != final_identity):
            scan_complete = False
            stop_reason = "inventory_changed_or_unverified"
            reasons = inventory.setdefault("reasons", [])
            if final_inventory.get("complete") is not True:
                reasons.extend(reason for reason in final_inventory.get("reasons", []) if reason not in reasons)
                examples = inventory.setdefault("examples", {})
                for reason, paths in final_inventory.get("examples", {}).items():
                    bucket = examples.setdefault(reason, [])
                    for path in paths:
                        if path not in bucket:
                            if len(bucket) < 3:
                                bucket.append(path)
                            else:
                                inventory["examples_truncated"] = True
                inventory["examples_truncated"] = bool(
                    inventory.get("examples_truncated") or final_inventory.get("examples_truncated")
                )
                if not reasons:
                    reasons.append("inventory_coverage_unknown")
            elif not isinstance(initial_identity, dict) or not isinstance(final_identity, dict):
                reasons.append("inventory_evidence_missing")
            elif "workspace_changed" not in reasons:
                reasons.append("workspace_changed")

    if scanned_files == 0 and scan_complete and not inventory.get("excluded_link_paths", 0):
        scan_complete = False
        stop_reason = "no_files_scanned"

    high_count = sum(1 for f in findings if f.get("severity") == "HIGH")
    med_count = sum(1 for f in findings if f.get("severity") == "MEDIUM")
    test_findings = []
    for finding in findings:
        rel_path = str(finding.get("path", ""))
        is_test = rel_path.casefold().startswith("tests/") or path_type(rel_path).name.casefold().startswith("test_")
        finding["is_test"] = is_test
        finding["classification"] = "untriaged"
        if is_test:
            test_findings.append(finding)
    untriaged_high = sum(
        1 for finding in findings
        if finding.get("severity") == "HIGH"
    )

    return {
        "success": True,
        "root": str(resolved_root),
        "findings_count": len(findings),
        "high_severity_count": high_count,
        "medium_severity_count": med_count,
        "untriaged_high_severity_count": untriaged_high,
        "test_findings_count": len(test_findings),
        "findings_present": bool(findings),
        "release_blocking_findings": untriaged_high,
        "triage_complete": not findings,
        "scanned_files": scanned_files,
        "eligible_files": eligible_files,
        "eligible_files_total": None,
        "skipped_files": skipped_files,
        "scanned_bytes": scanned_bytes,
        "scan_complete": scan_complete,
        "inventory_incomplete_reasons": inventory.get("reasons", []),
        "inventory_incomplete_examples": inventory.get("examples", {}),
        "inventory_examples_truncated": bool(inventory.get("examples_truncated", False)),
        "limit_reached": limit_reached,
        "stop_reason": stop_reason,
        "scan_errors": scan_errors,
        "coverage_scope": "project-filtered repository files; symlinks and reparse points excluded; counts cover visited entries",
        "is_clean": not findings and scan_complete,
        "findings": findings[:limit],
    }

