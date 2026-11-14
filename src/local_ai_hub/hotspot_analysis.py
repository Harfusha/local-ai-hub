from __future__ import annotations

import ast
import math
import os
import shutil
import stat
import subprocess
import time
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .process_utils import ProcessCancelledError, ProcessCleanupUnverifiedError

_HOTSPOT_ALGORITHM = "git-recency-half-life-90d-v1"
_HOTSPOT_GIT_COMMIT_LIMIT = 5_000
_HOTSPOT_PATH_LIMIT = 10_000
_HOTSPOT_FILE_LIMIT = 100
_HOTSPOT_FILE_BYTES_LIMIT = 262_144
_HOTSPOT_TOTAL_BYTES_LIMIT = 4_194_304
_HOTSPOT_ANALYSIS_SECONDS = 8.0


def find_hotspots(
    root: str,
    days: int,
    limit: int,
    *,
    root_resolver: Callable[[str], str],
    is_symlink_or_reparse_point: Callable[[Path], bool],
    git_insight_stream_limit: int,
    run_hidden_fn: Callable[..., Any],
    clean_git_env_fn: Callable[..., Any],
) -> dict[str, Any]:
    """Rank Git-touched files by bounded recency-weighted churn and complexity."""
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 3650:
        return {"success": False, "status_code": 400, "terminal": True, "retryable": False,
                "error": "days must be an integer from 1 to 3650"}
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        return {"success": False, "status_code": 400, "terminal": True, "retryable": False,
                "error": "limit must be an integer from 1 to 50"}
    resolved = root_resolver(root)
    git_exe = shutil.which("git") or "git"

    # The service-level repository cache keys this operation by the current
    # repository fingerprint. Do not consult the older root/days-only table:
    # it cannot detect changed HEADs or current-file contents.

    deadline = time.monotonic() + _HOTSPOT_ANALYSIS_SECONDS
    now = time.time()
    cutoff = int(now - days * 86_400)
    argv = [
        git_exe, "-C", resolved, "--literal-pathspecs", "-c", "core.pager=cat",
        "log", f"-n{_HOTSPOT_GIT_COMMIT_LIMIT + 1}", f"--since-as-filter=@{cutoff}",
        "--format=%x00LAH_HOTSPOT:%ct%x00", "--name-only", "-z", "--no-merges",
        "--no-renames", "--no-ext-diff", "--no-textconv", "--end-of-options", "HEAD", "--",
    ]
    incomplete: set[str] = set()
    churn_counts: dict[str, int] = defaultdict(int)
    weighted_counts: dict[str, float] = defaultdict(float)
    try:
        res = run_hidden_fn(
            argv,
            cwd=resolved,
            capture_output=True,
            text=False,
            stdin=subprocess.DEVNULL,
            timeout=max(0.1, deadline - time.monotonic()),
            max_output_bytes=git_insight_stream_limit,
            env=clean_git_env_fn(extra_env={
                "GIT_PAGER": "cat", "PAGER": "cat", "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "diff.external",
                "GIT_CONFIG_VALUE_0": "",
            }),
        )
        if getattr(res, "returncode", 1) != 0:
            incomplete.add("git_history_failed")
        if getattr(res, "stdout_truncated", False) or getattr(res, "stderr_truncated", False):
            incomplete.add("git_output_truncated")
        raw_output = getattr(res, "stdout", b"")
        if not isinstance(raw_output, bytes):
            incomplete.add("git_output_malformed")
            raw_output = b""
        segments = raw_output.split(b"\0LAH_HOTSPOT:")
        if segments and not segments[0].strip(b"\r\n"):
            segments = segments[1:]
        if len(segments) > _HOTSPOT_GIT_COMMIT_LIMIT:
            incomplete.add("commit_limit_reached")
        for segment in segments[:_HOTSPOT_GIT_COMMIT_LIMIT]:
            if time.monotonic() >= deadline:
                incomplete.add("analysis_deadline")
                break
            try:
                # The explicit timestamp terminator is followed by Git's
                # -z record terminator before its filename framing newline.
                timestamp_raw, separator, files_raw = segment.partition(b"\0\0")
                timestamp = int(timestamp_raw.strip())
                if not separator or timestamp < cutoff:
                    raise ValueError("malformed commit record")
                # Git inserts one formatting newline around each NUL-delimited
                # name list. Remove only those framing bytes; preserve filename newlines.
                if files_raw.startswith(b"\n"):
                    files_raw = files_raw[1:]
                if files_raw.endswith(b"\n"):
                    files_raw = files_raw[:-1]
                per_commit: set[str] = set()
                path_offset = 0
                path_count = 0
                while path_offset <= len(files_raw):
                    if path_count >= _HOTSPOT_PATH_LIMIT:
                        if path_offset < len(files_raw):
                            incomplete.add("path_limit_reached")
                        break
                    if path_count % 64 == 0 and time.monotonic() >= deadline:
                        incomplete.add("analysis_deadline")
                        break
                    separator_at = files_raw.find(b"\0", path_offset)
                    if separator_at < 0:
                        raw_path = files_raw[path_offset:]
                        path_offset = len(files_raw) + 1
                    else:
                        raw_path = files_raw[path_offset:separator_at]
                        path_offset = separator_at + 1
                    path_count += 1
                    if not raw_path:
                        continue
                    relative = raw_path.decode("utf-8", "strict").replace("\\", "/")
                    pure_path = PurePosixPath(relative)
                    if pure_path.is_absolute() or any(part in {"..", ""} for part in pure_path.parts):
                        incomplete.add("unsafe_git_path")
                        continue
                    if any(part.lower() in {".git", "vendor", "node_modules", "dist", "build"} for part in pure_path.parts):
                        continue
                    relative_path = pure_path.as_posix()
                    if relative_path in per_commit:
                        continue
                    if relative_path not in churn_counts and len(churn_counts) >= _HOTSPOT_PATH_LIMIT:
                        incomplete.add("path_limit_reached")
                        break
                    per_commit.add(relative_path)
                age_days = max(0.0, (now - float(timestamp)) / 86_400.0)
                weight = 0.5 ** (age_days / 90.0)
                for relative in per_commit:
                    churn_counts[relative] += 1
                    weighted_counts[relative] += weight
            except (UnicodeDecodeError, ValueError, OverflowError):
                incomplete.add("git_output_malformed")
        if len(segments) > _HOTSPOT_GIT_COMMIT_LIMIT:
            incomplete.add("commit_limit_reached")
        if time.monotonic() >= deadline:
            incomplete.add("analysis_deadline")
    except (ProcessCancelledError, ProcessCleanupUnverifiedError, subprocess.TimeoutExpired, OSError, ValueError) as exc:
        incomplete.add(f"git_history_{type(exc).__name__}")

    if not churn_counts and incomplete:
        return {
            "success": False,
            "root": resolved,
            "days": days,
            "count": 0,
            "hotspots": [],
            "algorithm": _HOTSPOT_ALGORITHM,
            "complete": False,
            "incomplete_reasons": sorted(incomplete),
            "recency_half_life_days": 90,
        }

    hotspots: list[dict[str, Any]] = []
    candidates = sorted(
        weighted_counts,
        key=lambda file_rel: (-weighted_counts[file_rel], file_rel),
    )
    if len(candidates) > _HOTSPOT_FILE_LIMIT:
        incomplete.add("file_limit_reached")
    total_bytes = 0
    reserved_bytes = 0
    analyzed_files = 0
    canonical_root = Path(resolved).resolve(strict=True)
    for file_rel in candidates[:_HOTSPOT_FILE_LIMIT]:
        if time.monotonic() >= deadline:
            incomplete.add("analysis_deadline")
            break
        full_p = Path(resolved) / file_rel
        fd = -1
        content_buffer = bytearray()
        try:
            current_component = canonical_root
            for part in PurePosixPath(file_rel).parts:
                current_component = current_component / part
                if is_symlink_or_reparse_point(current_component):
                    raise ValueError("reparse_point")
            before = os.stat(full_p, follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("not_regular")
            canonical_file = full_p.resolve(strict=True)
            canonical_file.relative_to(canonical_root)
            size = before.st_size
            if size > _HOTSPOT_FILE_BYTES_LIMIT:
                incomplete.add("file_byte_limit_reached")
                continue
            reservation = size + 1
            if reserved_bytes + reservation > _HOTSPOT_TOTAL_BYTES_LIMIT:
                incomplete.add("aggregate_byte_limit_reached")
                break
            reserved_bytes += reservation
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
            if getattr(os, "O_NOFOLLOW", 0):
                flags |= os.O_NOFOLLOW
            fd = os.open(full_p, flags)
            opened = os.fstat(fd)
            if (
                not stat.S_ISREG(opened.st_mode)
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
            ):
                raise ValueError("file_identity_changed")
            opened_path = Path(full_p).resolve(strict=True)
            opened_path.relative_to(canonical_root)
            source = os.fdopen(fd, "rb", buffering=0)
            fd = -1
            deadline_expired_during_read = False
            with source:
                remaining_read = reservation
                while remaining_read:
                    if time.monotonic() >= deadline:
                        incomplete.add("analysis_deadline")
                        deadline_expired_during_read = True
                        break
                    chunk = source.read(min(65_536, remaining_read))
                    if not chunk:
                        break
                    content_buffer.extend(chunk)
                    total_bytes += len(chunk)
                    remaining_read -= len(chunk)
                after = os.fstat(source.fileno())
            if deadline_expired_during_read:
                continue
            current_path_stat = os.stat(full_p, follow_symlinks=False)
            current_path = full_p.resolve(strict=True)
            current_path.relative_to(canonical_root)
            before_state = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            opened_state = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
            after_state = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            path_state = (
                current_path_stat.st_dev, current_path_stat.st_ino, current_path_stat.st_size,
                current_path_stat.st_mtime_ns, current_path_stat.st_ctime_ns,
            )
            # Windows path stat and handle stat expose different ctime
            # semantics. Compare each source with its own earlier sample.
            if (
                before_state != path_state
                or opened_state != after_state
                or (current_path_stat.st_dev, current_path_stat.st_ino) != (after.st_dev, after.st_ino)
                or current_path != canonical_file
                or is_symlink_or_reparse_point(full_p)
            ):
                incomplete.add("file_changed_during_read")
                continue
            content_bytes = bytes(content_buffer)
            if len(content_buffer) > size:
                incomplete.add("file_grew_during_read")
                continue
            content = content_bytes.decode("utf-8", "strict")
            analyzed_files += 1
        except UnicodeDecodeError:
            incomplete.add("file_decode_failed")
            continue
        except ValueError as exc:
            incomplete.add("reparse_point_skipped" if str(exc) == "reparse_point" else "file_identity_changed")
            continue
        except (OSError, RuntimeError):
            incomplete.add("current_file_unavailable")
            continue
        finally:
            if fd >= 0:
                os.close(fd)
        comp_score = 1
        loc = 0
        if time.monotonic() >= deadline:
            incomplete.add("analysis_deadline")
            continue
        try:
            loc = len(content.splitlines())
            if full_p.suffix == ".py":
                if time.monotonic() >= deadline:
                    incomplete.add("analysis_deadline")
                    continue
                tree = ast.parse(content, filename=file_rel)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.ExceptHandler, ast.With, ast.Match)):
                        comp_score += 1
            else:
                comp_score = max(1, loc // 15)
        except Exception:
            incomplete.add("complexity_parse_failed")
            comp_score = max(1, loc // 20)

        raw_churn = churn_counts[file_rel]
        recency_weighted_churn = round(weighted_counts[file_rel], 6)
        hotspot_index = round(recency_weighted_churn * math.log2(1.0 + float(comp_score)), 2)
        hotspots.append({
            "file": file_rel,
            "path": file_rel,
            "churn": raw_churn,
            "churn_commits": raw_churn,
            "recency_weighted_churn": recency_weighted_churn,
            "complexity": comp_score,
            "lines_of_code": loc,
            "debt_score": hotspot_index,
            "hotspot_score": hotspot_index,
            "risk_level": "critical" if hotspot_index >= 50 else ("high" if hotspot_index >= 20 else "moderate"),
        })

    hotspots.sort(key=lambda x: x["hotspot_score"], reverse=True)
    res_data = {
        "success": True,
        "root": resolved,
        "days": days,
        "algorithm": _HOTSPOT_ALGORITHM,
        "recency_half_life_days": 90,
        "recency_weighting": "sum(0.5 ** (commit_age_days / 90)) over commits in the requested day window",
        "complete": not incomplete,
        "incomplete_reasons": sorted(incomplete),
        "analysis": {
            "git_commits_scanned": min(len(segments) if "segments" in locals() else 0, _HOTSPOT_GIT_COMMIT_LIMIT),
            "files_seen": len(candidates),
            "files_analyzed": analyzed_files,
            "bytes_read": total_bytes,
            "bytes_reserved": reserved_bytes,
            "commit_limit": _HOTSPOT_GIT_COMMIT_LIMIT,
            "file_limit": _HOTSPOT_FILE_LIMIT,
            "per_file_bytes_limit": _HOTSPOT_FILE_BYTES_LIMIT,
            "aggregate_bytes_limit": _HOTSPOT_TOTAL_BYTES_LIMIT,
        },
        "count": len(hotspots),
        "hotspots": hotspots,
    }
    res_data["hotspots"] = hotspots[:limit]
    res_data["count"] = len(res_data["hotspots"])
    return res_data
