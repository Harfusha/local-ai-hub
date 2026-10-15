"""Bounded, read-only source slices confined to the adapter workspace."""
from __future__ import annotations

import hashlib
import io
import os
import stat
from pathlib import Path
from typing import Any

MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_SOURCE_LINES = 200
SOURCE_SLICE_FIELDS = (
    "action", "path", "relative_path", "file_sha256", "line_start", "line_end",
    "requested_line_end", "total_lines", "text", "truncated", "complete",
)


def read_source_slice(
    workspace: str, path: str, *, line_start: int = 1,
    line_end: int = 0, max_chars: int = 4000,
) -> dict[str, Any]:
    """Return exact selected text with its full source digest, or a typed error."""
    def failure(message: str) -> dict[str, Any]:
        return {"success": False, "action": "source", "error": message,
                "terminal": True, "retryable": False}

    if not isinstance(path, str) or not path or len(path) > 32768 or "\x00" in path:
        return failure("path must be a non-empty bounded source path")
    if type(line_start) is not int or line_start < 1:
        return failure("line_start must be a positive integer")
    if type(line_end) is not int or line_end < 0:
        return failure("line_end must be a non-negative integer")
    requested_end = line_end or line_start + 79
    if requested_end < line_start or requested_end - line_start + 1 > MAX_SOURCE_LINES:
        return failure(f"source range must contain 1 through {MAX_SOURCE_LINES} lines")
    if type(max_chars) is not int or not 512 <= max_chars <= 12000:
        return failure("max_chars must be between 512 and 12000")
    try:
        root = Path(workspace).resolve(strict=True)
        if not root.is_dir():
            return failure("workspace root must be a directory")
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        target = candidate.resolve(strict=True)
        relative = target.relative_to(root)
        if not target.is_file():
            return failure("source path must name a regular file")
        path_before = target.stat()
        # Nonblocking/no-follow flags also reject or avoid hanging on swapped
        # special files where the host provides these flags.
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(target, flags)
        with os.fdopen(descriptor, "rb") as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode):
                return failure("source path must name a regular file")
            if before.st_size > MAX_SOURCE_BYTES:
                return failure("source file exceeds the 4 MiB read bound")
            data = source.read(MAX_SOURCE_BYTES + 1)
            after = os.fstat(source.fileno())
        if len(data) > MAX_SOURCE_BYTES:
            return failure("source file exceeds the 4 MiB read bound")
        current_target = candidate.resolve(strict=True)
        current_target.relative_to(root)
        current = current_target.stat()
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if (
            current_target != target
            or identity(path_before) != identity(current)
            or identity(before) != identity(after)
        ):
            return failure("source changed while reading; slice not returned")
        if b"\x00" in data:
            return failure("source is binary or uses an unsupported encoding")
        content = data.decode("utf-8", errors="strict")
    except (OSError, ValueError, RuntimeError) as exc:
        return failure(f"source read rejected: {type(exc).__name__}")

    selected_parts: list[str] = []
    total_lines = 0
    selected_chars = 0
    # A newline-dense file must not allocate millions of tiny line strings.
    with io.StringIO(content, newline="") as stream:
        for total_lines, line in enumerate(stream, 1):
            if line_start <= total_lines <= requested_end:
                selected_chars += len(line)
                room = max_chars - sum(len(part) for part in selected_parts)
                if room > 0:
                    selected_parts.append(line[:room])
    if line_start > total_lines and total_lines:
        return failure("line_start exceeds the source line count")
    text = "".join(selected_parts)
    truncated = len(text) != selected_chars
    returned_end = line_start + len(text.splitlines()) - 1
    return {
        "success": True, "action": "source", "path": str(target),
        "relative_path": relative.as_posix(), "file_sha256": hashlib.sha256(data).hexdigest(),
        "line_start": line_start, "line_end": returned_end,
        "requested_line_end": requested_end, "total_lines": total_lines,
        "text": text, "truncated": truncated, "complete": not truncated,
    }
