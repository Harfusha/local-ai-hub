from __future__ import annotations

import math
import os
import stat
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any

from .deterministic_test_paths import is_test_file as _is_test_file
from .process_utils import (
    ProcessCancelledError,
    ProcessCleanupUnverifiedError,
    clean_git_env,
    run_hidden,
)
from .secret_history import parse_git_patch_output
from .secret_scan_config import (
    _SECRET_SCAN_MAX_ENTRIES,
    _SECRET_SCAN_MAX_FILES,
    _SECRET_SCAN_MAX_FILE_BYTES,
    _SECRET_SCAN_MAX_TOTAL_BYTES,
    _SECRET_SCAN_MAX_LINE_BYTES,
    _SECRET_SCAN_MAX_SECONDS,
    _SECRET_SCAN_MAX_FINDINGS,
    _SECRET_SCAN_PATTERNS,
)

def scan_secrets(
        self,
        root: str,
        path: str | None = None,
        *,
        scan_git_history: bool = False,
        commit_depth: int = 20,
        max_entries: int = _SECRET_SCAN_MAX_ENTRIES,
        max_files: int = _SECRET_SCAN_MAX_FILES,
        max_file_bytes: int = _SECRET_SCAN_MAX_FILE_BYTES,
        max_total_bytes: int = _SECRET_SCAN_MAX_TOTAL_BYTES,
        max_line_bytes: int = _SECRET_SCAN_MAX_LINE_BYTES,
        max_seconds: float = _SECRET_SCAN_MAX_SECONDS,
        max_findings: int = _SECRET_SCAN_MAX_FINDINGS,
        patterns: tuple = _SECRET_SCAN_PATTERNS,
        run_hidden_callable=run_hidden,
    ) -> dict[str, Any]:
        """Scan repository or specific file for leaked secrets, API keys, and credentials."""
        if scan_git_history and (
            not isinstance(commit_depth, int) or isinstance(commit_depth, bool)
            or not 1 <= commit_depth <= 100
        ):
            return {
                "success": False, "error": "commit_depth must be an integer from 1 to 100",
                "error_code": "invalid_commit_depth",
                "scan_complete": False, "clean": False, "scanned_git_history": False,
                "git_history_status": "invalid_commit_depth",
                "status_code": 400, "terminal": True, "retryable": False,
            }
        p_root = Path(self._root(root))
        if not p_root.is_dir():
            return {"success": False, "error": f"root not found: {root}"}
        scan_root = p_root.resolve(strict=True)
        started = time.monotonic()
        deadline = started + max_seconds
        history_pathspec: str | None = None
        if scan_git_history and path is not None:
            requested_history_path = Path(path)
            history_target = requested_history_path if requested_history_path.is_absolute() else scan_root / requested_history_path
            try:
                normalized_history_path = history_target.resolve(strict=False)
                history_pathspec = normalized_history_path.relative_to(scan_root).as_posix()
                if not history_pathspec or history_pathspec == ".":
                    raise ValueError
            except (OSError, ValueError):
                return {
                    "success": False, "error": "history path must resolve within scan root",
                    "error_code": "invalid_pathspec",
                    "scan_complete": False, "clean": False, "scanned_git_history": False,
                    "git_history_status": "invalid_pathspec",
                    "status_code": 400, "terminal": True, "retryable": False,
                }
        excluded = {".git", "node_modules", "venv", ".venv", "tool-envs", "state", "build", "dist", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox"}
        binary_suffixes = {".png", ".jpg", ".jpeg", ".exe", ".bin", ".whl", ".pyc", ".db", ".sqlite3", ".zip", ".tar", ".gz", ".lock", ".wasm"}
        findings: list[dict[str, Any]] = []
        errors: list[str] = []
        skipped_files = 0
        visited_entries = 0
        visited_files = 0
        eligible_files = 0
        bytes_read = 0
        limits_hit: list[str] = []
        complete = True
        patterns = patterns
        placeholders = {"EXAMPLE", "DUMMY", "SAMPLE", "PLACEHOLDER", "CHANGE_ME", "REPLACE_ME", "YOUR_KEY", "YOUR_API_KEY", "YOUR_SECRET", "MY_SECRET", "FAKETOKEN", "123456789", "ABCDEFGHIJKL"}

        def _shannon_entropy(value: str) -> float:
            if not value:
                return 0.0
            counts = Counter(value)
            length = len(value)
            return -sum((count / length) * math.log2(count / length) for count in counts.values())

        def _placeholder(token: str) -> bool:
            return token.upper() in placeholders

        def _record_error(code: str) -> None:
            nonlocal complete
            complete = False
            if len(errors) < 20:
                errors.append(code)

        def _scan_line(
            raw_line: bytes, rel: str, line_no: int, *,
            source: str = "working_tree", git_commit: str | None = None,
            git_change: str | None = None,
        ) -> bool:
            nonlocal complete
            if len(findings) >= max_findings:
                limits_hit.append("findings")
                complete = False
                return True
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            is_test = _is_test_file(rel)
            for rule_name, label, pattern, severity in patterns:
                for match in pattern.finditer(line):
                    token = match.group(1) if match.groups() else match.group(0)
                    entropy = _shannon_entropy(token)
                    masked = f"{token[:4]}***{token[-4:]}" if len(token) > 8 else "***"
                    findings.append({
                        "file": rel, "line": line_no, "rule": rule_name,
                        "description": label, "secret_type": rule_name,
                        "severity": severity, "is_test": is_test,
                        "is_placeholder": _placeholder(token),
                        "triage_status": "untriaged", "entropy": round(entropy, 2),
                        "match": masked, "redacted_secret": masked,
                        "redacted_snippet": "credential-like value omitted",
                        "source": source,
                        **({"git_commit": git_commit, "git_change": git_change} if git_commit else {}),
                    })
                    if len(findings) >= max_findings:
                        limits_hit.append("findings")
                        complete = False
                        return True
            return False

        if path is not None:
            requested = Path(path)
            target = requested if requested.is_absolute() else scan_root / requested
            try:
                resolved = target.resolve(strict=True)
                resolved.relative_to(scan_root)
                if target.is_symlink() or not resolved.is_file():
                    raise ValueError
                scan_files = [resolved]
            except (OSError, ValueError):
                scan_files = []
                _record_error("requested_path_unreadable_or_outside_root")
        else:
            scan_files = []
            pending = [scan_root]
            while pending:
                if time.monotonic() >= deadline:
                    limits_hit.append("time")
                    complete = False
                    break
                current = pending.pop()
                try:
                    current.relative_to(scan_root)
                    with os.scandir(current) as entries:
                        for entry in entries:
                            if time.monotonic() >= deadline:
                                limits_hit.append("time")
                                complete = False
                                pending.clear()
                                break
                            visited_entries += 1
                            if visited_entries > max_entries:
                                limits_hit.append("visited_entries")
                                complete = False
                                pending.clear()
                                break
                            if entry.name in excluded:
                                skipped_files += 1
                                continue
                            if entry.is_symlink() or getattr(os.path, "isjunction", lambda _p: False)(entry.path):
                                skipped_files += 1
                                _record_error("linked_path_omitted")
                                continue
                            candidate = Path(entry.path)
                            if entry.is_dir(follow_symlinks=False):
                                pending.append(candidate)
                            elif entry.is_file(follow_symlinks=False):
                                scan_files.append(candidate)
                except (OSError, PermissionError):
                    _record_error("directory_unreadable")

        for candidate in scan_files:
            if time.monotonic() >= deadline:
                limits_hit.append("time")
                complete = False
                break
            if visited_files >= max_files:
                limits_hit.append("visited_files")
                complete = False
                break
            visited_files += 1
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(scan_root)
                if candidate.is_symlink() or not resolved.is_file():
                    skipped_files += 1
                    _record_error("file_changed_or_linked_during_scan")
                    continue
                rel = resolved.relative_to(scan_root).as_posix()
                if resolved.suffix.lower() in binary_suffixes:
                    skipped_files += 1
                    continue
                before = os.stat(candidate, follow_symlinks=False)
                if not stat.S_ISREG(before.st_mode):
                    skipped_files += 1
                    _record_error("non_regular_file_omitted")
                    continue
                flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
                if getattr(os, "O_NOFOLLOW", 0):
                    flags |= os.O_NOFOLLOW
                fd = os.open(candidate, flags)
                try:
                    opened = os.fstat(fd)
                    if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                        skipped_files += 1
                        _record_error("file_identity_changed_or_non_regular")
                        continue
                    opened_path = candidate.resolve(strict=True)
                    opened_path.relative_to(scan_root)
                    path_stat = os.stat(candidate, follow_symlinks=False)
                    if (path_stat.st_dev, path_stat.st_ino) != (opened.st_dev, opened.st_ino):
                        skipped_files += 1
                        _record_error("file_path_changed_or_outside_root")
                        continue
                    source = os.fdopen(fd, "rb")
                    fd = -1
                finally:
                    if fd >= 0:
                        os.close(fd)
                eligible_files += 1
                with source:
                    file_bytes = 0
                    line_no = 0
                    while True:
                        if time.monotonic() >= deadline:
                            limits_hit.append("time")
                            complete = False
                            break
                        remaining = min(
                            max_file_bytes - file_bytes,
                            max_total_bytes - bytes_read,
                        )
                        if remaining <= 0:
                            limits_hit.append("file_bytes" if file_bytes >= max_file_bytes else "aggregate_bytes")
                            complete = False
                            break
                        raw_line = source.readline(min(max_line_bytes + 1, remaining))
                        if not raw_line:
                            break
                        file_bytes += len(raw_line)
                        bytes_read += len(raw_line)
                        line_no += 1
                        line_content = raw_line.rstrip(b"\r\n")
                        if len(line_content) > max_line_bytes:
                            _record_error("line_exceeds_scan_limit")
                            if not raw_line.endswith(b"\n"):
                                while True:
                                    drain_left = min(
                                        max_file_bytes - file_bytes,
                                        max_total_bytes - bytes_read,
                                    )
                                    if drain_left <= 0:
                                        limits_hit.append("file_bytes" if file_bytes >= max_file_bytes else "aggregate_bytes")
                                        complete = False
                                        break
                                    drained = source.readline(min(8192, drain_left))
                                    if not drained:
                                        break
                                    file_bytes += len(drained)
                                    bytes_read += len(drained)
                                    if drained.endswith(b"\n"):
                                        break
                                    if time.monotonic() >= deadline:
                                        limits_hit.append("time")
                                        complete = False
                                        break
                                if not complete and limits_hit:
                                    break
                            continue
                        _scan_line(line_content, rel, line_no)
                        if len(findings) >= max_findings:
                            break
                    after = os.fstat(source.fileno())
                    opened_state = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
                    after_state = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    if opened_state != after_state:
                        _record_error("file_changed_during_scan")
                    current_path = candidate.resolve(strict=True)
                    current_path.relative_to(scan_root)
                    current = os.stat(candidate, follow_symlinks=False)
                    if (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino):
                        _record_error("file_path_changed_during_scan")
                    if after.st_size > max_file_bytes:
                        limits_hit.append("file_bytes")
                        complete = False
                    if not complete and limits_hit:
                        break
            except (OSError, UnicodeError, ValueError):
                _record_error("file_unreadable_or_outside_root")
            if not complete and limits_hit:
                break

        history_status = "not_requested"
        history_command_completed = False
        history_coverage: dict[str, Any] = {
            "scope": "not requested", "commits_scanned": 0, "bytes_read": 0,
            "max_commit_depth": 100, "max_bytes": max_total_bytes,
            "limitations": [],
        }
        if scan_git_history:
            history_coverage["scope"] = "changed text in the last requested commits reachable from HEAD; not the full historical tree"
            history_coverage["limitations"] = [
                "Only textual lines represented in ordinary patch hunks are scanned.",
                "Binary content, combined merge patches, and ambiguous paths are omitted and make coverage incomplete.",
                "History scanning covers at most the requested commit depth, not all refs or unreachable objects.",
                "Shallow-history boundaries and commits unreachable from HEAD may omit older or alternate history.",
            ]
            history_coverage["requested_commit_depth"] = commit_depth
            if len(findings) >= max_findings:
                history_status = "finding_limit_reached"
                limits_hit.append("findings")
                complete = False
                _record_error("git_history_finding_limit_reached")
            else:
                remaining_time = deadline - time.monotonic()
                remaining_bytes = max_total_bytes - bytes_read
                if remaining_time <= 0:
                    history_status = "time_budget_exhausted"
                    limits_hit.append("time")
                    _record_error("git_history_not_scanned_within_budget")
                elif remaining_bytes < 2048:
                    history_status = "aggregate_byte_budget_exhausted"
                    limits_hit.append("aggregate_bytes")
                    _record_error("git_history_not_scanned_within_budget")
                else:
                    per_stream_limit = min(8 * 1024 * 1024, remaining_bytes // 2)
                    argv = [
                        "git", "--literal-pathspecs", "--no-pager", "-C", str(scan_root),
                        "-c", "core.quotePath=true", "-c", "color.ui=false",
                        "log", "--no-color", "--no-ext-diff", "--no-textconv",
                        "--no-renames", "--no-notes", "--no-decorate", "--no-show-signature",
                        "--src-prefix=a/", "--dst-prefix=b/", "--unified=3",
                        "--patch", "--max-count=" + str(commit_depth),
                        "--format=%x00LAH_SECRET_SCAN_COMMIT:%H PARENTS:%P%x00", "--end-of-options", "HEAD", "--",
                    ]
                    if history_pathspec is not None:
                        argv.append(history_pathspec)
                    try:
                        process_result = run_hidden_callable(
                            argv, cwd=str(scan_root), capture_output=True, text=False,
                            stdin=subprocess.DEVNULL,
                            timeout=remaining_time, max_output_bytes=per_stream_limit,
                            env=clean_git_env(extra_env={
                                "GIT_PAGER": "cat", "PAGER": "cat", "GIT_TERMINAL_PROMPT": "0",
                                "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                            }),
                        )
                        stdout_ok = isinstance(process_result.stdout, bytes)
                        stderr_ok = isinstance(process_result.stderr, bytes)
                        stdout = process_result.stdout if stdout_ok else b""
                        stderr = process_result.stderr if stderr_ok else b""
                        history_coverage["bytes_read"] = len(stdout) + len(stderr)
                        history_coverage["discarded_output_bytes"] = int(
                            getattr(process_result, "discarded_output_bytes", 0) or 0
                        )
                        capture_bad = bool(
                            getattr(process_result, "stdout_truncated", False)
                            or getattr(process_result, "stderr_truncated", False)
                            or getattr(process_result, "output_capture_unconfirmed", False)
                            or getattr(process_result, "tree_termination_confirmed", True) is False
                            or getattr(process_result, "cleanup_confirmed", True) is False
                            or getattr(process_result, "discarded_output_bytes", 0)
                            or not stdout_ok or not stderr_ok
                            or len(stdout) + len(stderr) > remaining_bytes
                        )
                        if capture_bad:
                            history_status = "output_capture_incomplete"
                            limits_hit.append("history_output_bytes")
                            _record_error("git_history_capture_incomplete")
                        elif process_result.returncode != 0:
                            history_status = "command_failed"
                            _record_error("git_history_command_failed")
                        else:
                            history_command_completed = True
                            parsed = parse_git_patch_output(
                                stdout, deadline=deadline,
                                max_line_bytes=max_line_bytes,
                                finding_count=len(findings), max_findings=max_findings,
                                scan_line=_scan_line,
                            )
                            history_coverage["commits_scanned"] = parsed["commits_scanned"]
                            for code in parsed["errors"]:
                                _record_error(code)
                            if "git_history_line_exceeds_limit" in parsed["errors"]:
                                limits_hit.append("history_line_bytes")
                            history_status = parsed["status"]
                            if parsed["findings_limit"]:
                                limits_hit.append("findings")
                            elif history_status == "scanned":
                                history_status = "scanned_bounded_history"
                            elif history_status == "time_budget_exhausted":
                                limits_hit.append("time")
                            if history_coverage["bytes_read"] + bytes_read > max_total_bytes:
                                history_status = "aggregate_byte_limit_reached"
                                limits_hit.append("aggregate_bytes")
                                _record_error("git_history_exceeded_aggregate_byte_budget")
                    except (ProcessCancelledError, ProcessCleanupUnverifiedError, subprocess.SubprocessError, OSError, ValueError):
                        history_status = "process_failed_or_cleanup_unverified"
                        _record_error("git_history_process_or_cleanup_unverified")
                    if history_status != "scanned_bounded_history":
                        complete = False
                    if time.monotonic() >= deadline:
                        limits_hit.append("time")
                        complete = False
        leak_count = len(findings)
        return {
            "success": True,
            "leak_count": leak_count,
            "real_leaks_count": leak_count,
            "test_findings_count": sum(1 for item in findings if item["is_test"] or item["is_placeholder"]),
            "secrets_count": leak_count,
            "scanned_git_history": history_command_completed,
            "git_history_status": history_status,
            "clean": complete and leak_count == 0,
            "scan_complete": complete,
            "coverage": {
                "coverage_scope": "requested file only" if path is not None else "repository files excluding listed generated and cache directories",
                "excluded_dirs": sorted(excluded),
                "visited_entries": visited_entries,
                "visited_files": visited_files,
                "eligible_files": eligible_files,
                "skipped_files": skipped_files,
                "bytes_read": bytes_read,
                "limits_hit": sorted(set(limits_hit)),
                "errors": errors,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "max_entries": max_entries,
                "max_files": max_files,
                "max_file_bytes": max_file_bytes,
                "max_total_bytes": max_total_bytes,
                "max_seconds": max_seconds,
                "max_findings": max_findings,
                "git_history": history_coverage,
            },
            "findings": findings,
        }
