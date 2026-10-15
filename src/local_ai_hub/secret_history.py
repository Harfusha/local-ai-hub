"""Bounded parsing for ordinary textual Git patch output used by secret scans."""

from __future__ import annotations

import io
import re
import time
from collections.abc import Callable
from typing import Any


_COMMIT_MARKER = re.compile(
    rb"^\x00LAH_SECRET_SCAN_COMMIT:([0-9a-f]{40,64}) PARENTS:((?:[0-9a-f]{40,64}(?: [0-9a-f]{40,64})*)?)\x00$"
)
_HUNK = re.compile(rb"^@@ -([0-9]{1,20})(?:,([0-9]{1,20}))? \+([0-9]{1,20})(?:,([0-9]{1,20}))? @@(?: |$)")
_MAX_HUNK_NUMBER = (1 << 64) - 1


def _quoted_path_token(payload: bytes, offset: int) -> tuple[bytes, int] | None:
    if offset >= len(payload) or payload[offset:offset + 1] != b'"':
        return None
    offset += 1
    decoded = bytearray()
    escapes = {
        ord('"'): b'"', ord("\\"): b"\\", ord("a"): b"\a", ord("b"): b"\b",
        ord("t"): b"\t", ord("n"): b"\n", ord("v"): b"\v", ord("f"): b"\f", ord("r"): b"\r",
    }
    while offset < len(payload):
        byte = payload[offset]
        offset += 1
        if byte == ord('"'):
            return bytes(decoded), offset
        if byte != ord("\\"):
            decoded.append(byte)
            continue
        if offset >= len(payload):
            return None
        escaped = payload[offset]
        offset += 1
        if escaped in escapes:
            decoded.extend(escapes[escaped])
        elif ord("0") <= escaped <= ord("7") and offset + 1 < len(payload):
            octal = bytes((escaped, payload[offset], payload[offset + 1]))
            if any(byte < ord("0") or byte > ord("7") for byte in octal):
                return None
            value = int(octal, 8)
            if value > 0xFF:
                return None
            decoded.append(value)
            offset += 2
        else:
            return None
    return None


def _patch_path(header: bytes) -> str | None:
    payload = header[len(b"diff --git "):]
    quoted_old = _quoted_path_token(payload, 0)
    quoted_new = (
        _quoted_path_token(payload, quoted_old[1] + 1)
        if quoted_old and payload[quoted_old[1]:quoted_old[1] + 1] == b" " else None
    )
    if quoted_old and quoted_new and quoted_new[1] == len(payload):
        left, right = quoted_old[0], quoted_new[0]
    elif payload.startswith(b'"'):
        return None
    else:
        separators = [index for index in range(len(payload)) if payload.startswith(b" b/", index)]
        if len(separators) != 1:
            return None
        split = separators[0]
        left, right = payload[:split], payload[split + 1:]
    if not left.startswith(b"a/") or not right.startswith(b"b/"):
        return None
    old_raw, new_raw = left[2:], right[2:]
    if old_raw != new_raw or not old_raw or any(byte < 32 for byte in old_raw):
        return None
    try:
        value = old_raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    if any(ord(char) < 32 for char in value) or value.startswith(("/", "-", ":")) or any(
        part in {"", ".", ".."} for part in value.split("/")
    ):
        return None
    return value


def parse_git_patch_output(
    output: bytes,
    *,
    deadline: float,
    max_line_bytes: int,
    finding_count: int,
    max_findings: int,
    scan_line: Callable[..., bool],
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Parse bounded captured patches; malformed or omitted hunks fail closed."""
    status = "scanned"
    errors: list[str] = []
    commits: set[str] = set()
    stream = io.BytesIO(output)
    commit_id: str | None = None
    path = "<history path unavailable>"
    path_known = False
    unsupported_patch = False
    patch_hunk_started = False
    in_hunk = False
    old_line = new_line = old_remaining = new_remaining = 0

    def mark(code: str) -> None:
        nonlocal status
        if status not in {"time_budget_exhausted", "finding_limit_reached"}:
            status = "incomplete_patch"
        if code not in errors:
            errors.append(code)

    def finish_hunk() -> None:
        nonlocal in_hunk
        if in_hunk and (old_remaining or new_remaining):
            mark("git_history_hunk_line_count_mismatch")
        in_hunk = False

    def account_skipped_patch_line(line: bytes) -> None:
        nonlocal old_line, new_line, old_remaining, new_remaining, in_hunk
        if not in_hunk:
            return
        marker = line[:1]
        if marker == b"+" and new_remaining:
            new_line += 1
            new_remaining -= 1
        elif marker == b"-" and old_remaining:
            old_line += 1
            old_remaining -= 1
        elif marker == b" " and old_remaining and new_remaining:
            old_line += 1
            new_line += 1
            old_remaining -= 1
            new_remaining -= 1
        else:
            finish_hunk()
            mark("git_history_hunk_line_count_mismatch")
            return
        if old_remaining == 0 and new_remaining == 0:
            in_hunk = False

    def timed_out() -> bool:
        nonlocal status
        if monotonic() < deadline:
            return False
        status = "time_budget_exhausted"
        if "git_history_parse_time_budget_exhausted" not in errors:
            errors.append("git_history_parse_time_budget_exhausted")
        return True

    def read_bounded_line() -> tuple[bytes | None, bool]:
        """Return one bounded physical line and whether it exceeded the cap."""
        line = stream.readline(max_line_bytes + 2)  # allow CRLF without widening the content cap
        if not line:
            return None, False
        too_long = len(line.rstrip(b"\r\n")) > max_line_bytes
        if len(line) > max_line_bytes + 1 and not line.endswith(b"\n"):
            too_long = True
        if too_long and not line.endswith(b"\n"):
            while True:
                if timed_out():
                    return line, True
                remainder = stream.readline(8192)
                if not remainder or remainder.endswith(b"\n"):
                    break
        return line.rstrip(b"\r\n"), too_long

    if finding_count >= max_findings:
        return {"status": "finding_limit_reached", "errors": [], "commits_scanned": 0, "findings_limit": True}

    while True:
        if timed_out():
            finish_hunk()
            break
        history_line, too_long = read_bounded_line()
        if history_line is None:
            break
        if too_long:
            mark("git_history_line_exceeds_limit")
            account_skipped_patch_line(history_line)
            continue
        if history_line.startswith(b"\x00LAH_SECRET_SCAN_COMMIT:") and not _COMMIT_MARKER.match(history_line):
            finish_hunk()
            commit_id = None
            path = "<history path unavailable>"
            path_known = False
            unsupported_patch = True
            patch_hunk_started = False
            mark("git_history_malformed_commit_marker")
            continue
        marker = _COMMIT_MARKER.match(history_line)
        if marker:
            finish_hunk()
            commit_id = marker.group(1).decode("ascii")
            commits.add(commit_id)
            if len(marker.group(2).split()) > 1:
                mark("git_history_merge_commit_omitted")
            path = "<history path unavailable>"
            path_known = False
            unsupported_patch = False
            patch_hunk_started = False
            continue
        if history_line.startswith((b"diff --git ", b"diff --cc ", b"diff --combined ")):
            finish_hunk()
            patch_hunk_started = False
            if commit_id is None:
                mark("git_history_commit_context_missing")
            unsupported_patch = history_line.startswith((b"diff --cc ", b"diff --combined "))
            if unsupported_patch:
                mark("git_history_combined_patch_omitted")
            else:
                parsed_path = _patch_path(history_line)
                path_known = parsed_path is not None
                path = parsed_path or "<history path unavailable>"
                if not path_known:
                    mark("git_history_path_unresolved")
            continue
        if history_line.startswith(b"diff "):
            finish_hunk()
            mark("git_history_malformed_diff_header")
            continue
        if history_line.startswith((b"Binary files ", b"GIT binary patch")):
            finish_hunk()
            mark("git_history_binary_content_omitted")
            continue
        if history_line.startswith(b"@@@"):
            finish_hunk()
            unsupported_patch = True
            mark("git_history_combined_hunk_omitted")
            continue
        hunk = _HUNK.match(history_line)
        if hunk:
            finish_hunk()
            if not path_known or unsupported_patch or commit_id is None:
                mark("git_history_hunk_context_unresolved")
                continue
            numbers = [int(value) if value is not None else 1 for value in hunk.groups()]
            if any(value > _MAX_HUNK_NUMBER for value in numbers):
                patch_hunk_started = True
                mark("git_history_hunk_number_out_of_range")
                continue
            old_line, old_remaining, new_line, new_remaining = numbers
            patch_hunk_started = True
            in_hunk = bool(old_remaining or new_remaining)
            continue
        if history_line.startswith(b"@@"):
            finish_hunk()
            patch_hunk_started = True
            mark("git_history_malformed_hunk_header")
            continue
        if not in_hunk:
            if patch_hunk_started and history_line.startswith((b"+", b"-", b" ")):
                mark("git_history_hunk_line_count_mismatch")
            elif path_known and history_line.startswith((b"+", b"-", b" ")) and not history_line.startswith((b"+++ ", b"--- ")):
                mark("git_history_patch_line_without_hunk")
            continue
        if history_line.startswith(b"\\ No newline at end of file"):
            continue
        if history_line.startswith(b"+"):
            if new_remaining <= 0:
                finish_hunk()
                mark("git_history_hunk_line_count_mismatch")
                continue
            stopped = scan_line(
                history_line[1:], path, new_line, source="git_history",
                git_commit=commit_id, git_change="added",
            )
            new_line += 1
            new_remaining -= 1
        elif history_line.startswith(b"-"):
            if old_remaining <= 0:
                finish_hunk()
                mark("git_history_hunk_line_count_mismatch")
                continue
            stopped = scan_line(
                history_line[1:], path, old_line, source="git_history",
                git_commit=commit_id, git_change="removed",
            )
            old_line += 1
            old_remaining -= 1
        elif history_line.startswith(b" "):
            if old_remaining <= 0 or new_remaining <= 0:
                finish_hunk()
                mark("git_history_hunk_line_count_mismatch")
                continue
            old_line += 1
            new_line += 1
            old_remaining -= 1
            new_remaining -= 1
            stopped = False
        else:
            finish_hunk()
            mark("git_history_malformed_hunk")
            continue
        if old_remaining == 0 and new_remaining == 0:
            in_hunk = False
        if stopped or finding_count >= max_findings:
            status = "finding_limit_reached"
            errors.append("git_history_finding_limit_reached")
            break
    finish_hunk()
    return {
        "status": status,
        "errors": errors,
        "commits_scanned": len(commits),
        "findings_limit": status == "finding_limit_reached",
    }
