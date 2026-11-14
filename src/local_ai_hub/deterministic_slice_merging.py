from __future__ import annotations

import logging
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


def merge_overlapping_source_slices(
    repo_tools: Any, root: str, slices: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge nearby ranges and re-read exact text from a stable repository snapshot."""
    base = Path(root).resolve()
    validated: list[dict[str, Any]] = []
    for item in slices:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        start = item.get("start_line")
        end = item.get("end_line")
        digest = item.get("file_sha256")
        if (
            not isinstance(path, str)
            or not path
            or not isinstance(start, int)
            or isinstance(start, bool)
            or start < 1
            or not isinstance(end, int)
            or isinstance(end, bool)
            or end < start
            or not isinstance(digest, str)
            or not digest
        ):
            continue
        target = (base / path).resolve(strict=False)
        try:
            relative_path = target.relative_to(base).as_posix()
        except ValueError:
            continue
        validated.append(
            {
                "path": relative_path,
                "start_line": start,
                "end_line": end,
                "file_sha256": digest,
                "symbol_complete": bool(item.get("symbol_complete", False)),
            }
        )

    ordered = sorted(
        validated,
        key=lambda item: (
            item["path"],
            item["file_sha256"],
            item["start_line"],
            item["end_line"],
        ),
    )
    merged: list[dict[str, Any]] = []
    for current in ordered:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and previous["path"] == current["path"]
            and previous["file_sha256"] == current["file_sha256"]
            and current["start_line"] <= previous["end_line"] + 2
        ):
            previous["end_line"] = max(previous["end_line"], current["end_line"])
            previous["symbol_complete"] = (
                previous["symbol_complete"] and current["symbol_complete"]
            )
        else:
            merged.append(dict(current))

    snapshots: dict[str, tuple[str, list[str]] | None] = {}
    result: list[dict[str, Any]] = []
    for item in merged:
        path = item["path"]
        if path not in snapshots:
            try:
                snapshots[path] = repo_tools._read_snapshot(base / path)
            except OSError as read_exc:
                logger.debug("Merged evidence source skipped (%s)", type(read_exc).__name__)
                snapshots[path] = None
        snapshot = snapshots[path]
        if snapshot is None:
            continue
        digest, lines = snapshot
        start = item["start_line"]
        end = item["end_line"]
        if digest != item["file_sha256"] or not lines or end > len(lines):
            continue
        result.append(
            {
                **item,
                "text": "\n".join(
                    f"{line}: {lines[line - 1]}" for line in range(start, end + 1)
                ),
                "deterministic": True,
            }
        )
    return result
