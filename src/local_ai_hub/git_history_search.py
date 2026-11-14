from __future__ import annotations

import math
import os
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date as _datetime_date, datetime as _datetime, time as _datetime_time, timezone as _datetime_timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .process_utils import ProcessCancelledError, ProcessCleanupUnverifiedError


_GIT_INSIGHT_DEADLINE_SECONDS = 8.0
_GIT_INSIGHT_STREAM_LIMIT = 1_048_576
_GIT_HISTORY_QUERY_MAX_CHARS = 512
_GIT_HISTORY_AUTHOR_MAX_CHARS = 256
_GIT_HISTORY_PATH_MAX_CHARS = 4096
_GIT_HISTORY_COMMIT_LIMIT = 100


@dataclass(frozen=True)
class _HistoryFilters:
    clean_query: str
    clean_author: str
    since_epoch: float | None
    since_normalized: str | None
    until_epoch: float | None
    until_normalized: str | None
    pathspec: str | None


def _git_history_timestamp(value: Any, field: str, *, upper_bound: bool) -> tuple[float | None, str | None]:
    if value in (None, ""):
        return None, None
    if not isinstance(value, str) or len(value) > 64 or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError(f"{field} must be an ISO date or RFC3339 timestamp")
    raw = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        parsed_date = _datetime_date.fromisoformat(raw)
        parsed = _datetime.combine(
            parsed_date,
            _datetime_time.max if upper_bound else _datetime_time.min,
            tzinfo=_datetime_timezone.utc,
        )
    else:
        if not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
            raw,
            flags=re.IGNORECASE,
        ):
            raise ValueError(f"{field} must be an RFC3339 timestamp with an explicit timezone")
        normalized = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
        parsed = _datetime.fromisoformat(normalized)
        if parsed.tzinfo is None or "T" not in raw.upper():
            raise ValueError(f"{field} RFC3339 timestamp must include an explicit timezone")
        parsed = parsed.astimezone(_datetime_timezone.utc)
    timestamp = parsed.timestamp()
    return timestamp, parsed.isoformat().replace("+00:00", "Z")


def _git_history_pathspec(root: str, value: Any) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or len(value) > _GIT_HISTORY_PATH_MAX_CHARS:
        raise ValueError("path must be a bounded repository-relative literal path")
    normalized = value.replace("\\", "/")
    windows_path = PureWindowsPath(value)
    parts = PurePosixPath(normalized).parts
    if (
        not normalized
        or normalized.startswith("/")
        or windows_path.drive
        or windows_path.is_absolute()
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in normalized)
        or any(part in {"..", ""} for part in parts)
    ):
        raise ValueError("path must stay inside the repository root")
    canonical_root = Path(root).resolve(strict=True)
    candidate = (canonical_root / Path(*parts)).resolve(strict=False)
    try:
        candidate.relative_to(canonical_root)
    except ValueError as exc:
        raise ValueError("path must stay inside the repository root") from exc
    pathspec = PurePosixPath(*parts).as_posix()
    return None if pathspec == "." else pathspec


def _prepare_history_filters(
    resolved: str,
    query: str,
    max_commits: int,
    *,
    author: str | None,
    since: str | None,
    until: str | None,
    path: str | None,
) -> tuple[_HistoryFilters | None, dict[str, Any] | None]:
    if (
        not isinstance(query, str)
        or len(query) > _GIT_HISTORY_QUERY_MAX_CHARS
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in query)
    ):
        return None, {"success": False, "status_code": 400, "terminal": True, "retryable": False,
                      "error": "query must be a bounded literal string", "root": resolved}
    if isinstance(max_commits, bool) or not isinstance(max_commits, int) or not 1 <= max_commits <= _GIT_HISTORY_COMMIT_LIMIT:
        return None, {"success": False, "status_code": 400, "terminal": True, "retryable": False,
                      "error": f"max_commits must be an integer from 1 to {_GIT_HISTORY_COMMIT_LIMIT}", "root": resolved}
    if author is not None and (
        not isinstance(author, str)
        or len(author) > _GIT_HISTORY_AUTHOR_MAX_CHARS
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in author)
    ):
        return None, {"success": False, "status_code": 400, "terminal": True, "retryable": False,
                      "error": "author must be a bounded string", "root": resolved}

    try:
        since_epoch, since_normalized = _git_history_timestamp(since, "since", upper_bound=False)
        until_epoch, until_normalized = _git_history_timestamp(until, "until", upper_bound=True)
        pathspec = _git_history_pathspec(resolved, path)
    except (OSError, RuntimeError, TypeError, ValueError, OverflowError) as exc:
        return None, {"success": False, "status_code": 400, "terminal": True, "retryable": False,
                      "error": str(exc), "root": resolved}
    if since_epoch is not None and until_epoch is not None and since_epoch > until_epoch:
        return None, {"success": False, "status_code": 400, "terminal": True, "retryable": False,
                      "error": "since must be earlier than or equal to until", "root": resolved}

    return _HistoryFilters(
        clean_query=query.strip(),
        clean_author=author.strip() if isinstance(author, str) else "",
        since_epoch=since_epoch,
        since_normalized=since_normalized,
        until_epoch=until_epoch,
        until_normalized=until_normalized,
        pathspec=pathspec,
    ), None


def _merge_history_output(
    raw_output: bytes,
    match_type: str,
    commits: dict[str, dict[str, Any]],
    *,
    deadline: float,
    since_epoch: float | None,
    until_epoch: float | None,
) -> tuple[set[str], int]:
    incomplete: set[str] = set()
    fields = raw_output.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    if fields and fields[-1] in {b"\n", b"\r\n"}:
        fields.pop()
    if len(fields) % 4:
        incomplete.add(f"{match_type}_malformed_output")

    for index in range(0, len(fields) - 3, 4):
        if time.monotonic() >= deadline:
            incomplete.add("aggregate_deadline")
            break
        try:
            full_hash = fields[index].lstrip(b"\r\n").decode("ascii")
            commit_author = fields[index + 1].decode("utf-8", "strict")
            committed_at = fields[index + 2].decode("ascii", "strict")
            subject = fields[index + 3].decode("utf-8", "strict").strip("\r\n")
            if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", full_hash):
                raise ValueError("invalid commit hash")
            committed_dt = _datetime.fromisoformat(committed_at.replace("Z", "+00:00"))
            if committed_dt.tzinfo is None:
                raise ValueError("commit date has no timezone")
            committed_timestamp = committed_dt.timestamp()
            if since_epoch is not None and committed_timestamp < since_epoch:
                continue
            if until_epoch is not None and committed_timestamp > until_epoch:
                continue
        except (UnicodeDecodeError, ValueError, OverflowError):
            incomplete.add(f"{match_type}_malformed_output")
            continue

        current = commits.get(full_hash)
        if current is None:
            commits[full_hash] = {
                "commit": full_hash[:10],
                "full_hash": full_hash,
                "author": commit_author,
                "date": committed_dt.date().isoformat(),
                "subject": subject,
                "message": subject,
                "match_type": match_type,
                "_committed_timestamp": committed_timestamp,
                "_match_types": [match_type],
            }
        elif match_type not in current["_match_types"]:
            current["_match_types"].append(match_type)
    return incomplete, len(fields)


def search_git_history(
    root: str,
    query: str,
    max_commits: int = 20,
    *,
    author: str | None = None,
    since: str | None = None,
    until: str | None = None,
    path: str | None = None,
    root_resolver: Callable[[str], str],
    git_executable_fn: Callable[[str], str | None],
    run_hidden_fn: Callable[..., Any],
    clean_git_env_fn: Callable[..., dict[str, str]],
) -> dict[str, Any]:
    """Search bounded Git message and pickaxe history with explicit coverage."""
    resolved = root_resolver(root)
    git_exe = git_executable_fn("git") or "git"
    filters, validation_error = _prepare_history_filters(
        resolved, query, max_commits, author=author, since=since, until=until, path=path
    )
    if validation_error is not None:
        return validation_error
    assert filters is not None
    clean_query = filters.clean_query
    clean_author = filters.clean_author
    since_epoch = filters.since_epoch
    since_normalized = filters.since_normalized
    until_epoch = filters.until_epoch
    until_normalized = filters.until_normalized
    pathspec = filters.pathspec
    deadline = time.monotonic() + _GIT_INSIGHT_DEADLINE_SECONDS
    commits: dict[str, dict[str, Any]] = {}
    incomplete: set[str] = set()
    completed_searches = 0
    for match_type in ("message", "diff_content"):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            incomplete.add("aggregate_deadline")
            break
        fmt = "%H%x00%an%x00%cI%x00%s%x00"
        argv = [
            git_exe, "-C", resolved, "--literal-pathspecs",
            "-c", "diff.external=", "-c", "core.pager=cat", "log",
            f"-n{max_commits + 1}", f"--format={fmt}", "-i", "--fixed-strings",
            "--no-ext-diff", "--no-textconv", "--no-renames",
        ]
        if not clean_query and match_type == "diff_content":
            continue
        if match_type == "message":
            if clean_query:
                argv.append(f"--grep={clean_query}")
        else:
            argv.append(f"-S{clean_query}")
        if clean_author:
            argv.append(f"--author={clean_author}")
        if since_epoch is not None:
            argv.append(f"--since-as-filter=@{math.ceil(since_epoch)}")
        if until_epoch is not None:
            argv.append(f"--until=@{math.floor(until_epoch)}")
        argv.extend(("--end-of-options", "HEAD", "--"))
        if pathspec is not None:
            argv.append(pathspec)
        try:
            result = run_hidden_fn(
                argv,
                cwd=resolved,
                capture_output=True,
                text=False,
                stdin=subprocess.DEVNULL,
                timeout=remaining,
                max_output_bytes=_GIT_INSIGHT_STREAM_LIMIT,
                env=clean_git_env_fn(extra_env={
                    "GIT_PAGER": "cat", "PAGER": "cat", "GIT_TERMINAL_PROMPT": "0",
                    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                    "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "diff.external",
                    "GIT_CONFIG_VALUE_0": "",
                }),
            )
        except (ProcessCancelledError, ProcessCleanupUnverifiedError, subprocess.TimeoutExpired, OSError, ValueError) as exc:
            incomplete.add(f"{match_type}_search_{type(exc).__name__}")
            continue
        if getattr(result, "returncode", 1) != 0:
            incomplete.add(f"{match_type}_search_failed")
            continue
        if getattr(result, "stdout_truncated", False) or getattr(result, "stderr_truncated", False):
            incomplete.add(f"{match_type}_output_truncated")
        raw_output = getattr(result, "stdout", b"")
        if not isinstance(raw_output, bytes):
            incomplete.add(f"{match_type}_malformed_output")
            continue
        output_incomplete, field_count = _merge_history_output(
            raw_output,
            match_type,
            commits,
            deadline=deadline,
            since_epoch=since_epoch,
            until_epoch=until_epoch,
        )
        incomplete.update(output_incomplete)
        if field_count >= 4 * (max_commits + 1):
            incomplete.add("commit_limit_reached")
        completed_searches += 1

    if completed_searches < 2 and time.monotonic() >= deadline:
        incomplete.add("aggregate_deadline")
    ordered = sorted(
        commits.values(),
        key=lambda item: (-float(item["_committed_timestamp"]), item["full_hash"]),
    )
    if len(ordered) > max_commits:
        incomplete.add("commit_limit_reached")
    res_list = ordered[:max_commits]
    for item in res_list:
        item["match_type"] = ", ".join(item.pop("_match_types"))
        item.pop("_committed_timestamp", None)
    return {
        "success": completed_searches > 0,
        "root": resolved,
        "query": clean_query,
        "author": clean_author or None,
        "since": since_normalized,
        "until": until_normalized,
        "path": pathspec,
        "max_commits": max_commits,
        "count": len(res_list),
        "commits": res_list,
        "complete": not incomplete,
        "incomplete_reasons": sorted(incomplete),
    }
