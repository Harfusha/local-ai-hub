"""Evidence range grouping used by repository service projections."""

from __future__ import annotations

import hashlib
import math
import os
import stat
import time
from pathlib import Path, PurePosixPath
from typing import Callable, cast

from .process_utils import is_rooted_path, is_safe_path


EvidenceRecord = dict[str, object]

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_MERGED_LINES = 50_000


def _safe_line_number(val: object, default: int = 1, max_line: int = 5_000_000) -> int:
    if isinstance(val, bool) or val is None:
        return default
    try:
        n = int(cast(int | float | str, val))
        if 1 <= n <= max_line:
            return n
        return default
    except (ValueError, TypeError, OverflowError):
        return default


def _safe_score(val: object, default: float = 0.0) -> float:
    if isinstance(val, bool) or val is None:
        return default
    try:
        f = float(cast(int | float | str, val))
        return f if math.isfinite(f) else default
    except (ValueError, TypeError, OverflowError):
        return default


def merge_overlapping_line_ranges(
    ranges: list[tuple[int, int]], *, max_gap: int = 1
) -> list[tuple[int, int]]:
    """Merge overlapping or adjacent line intervals [start, end]."""
    valid = []
    for item in ranges:
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            start = _safe_line_number(item[0], -1)
            end = _safe_line_number(item[1], -1)
            if start == -1 or end == -1:
                continue
            if start > end:
                start, end = end, start
            valid.append((start, end))
    if not valid:
        return []
    sorted_ranges = sorted(valid, key=lambda item: (item[0], item[1]))
    merged = [sorted_ranges[0]]
    for start, end in sorted_ranges[1:]:
        previous_start, previous_end = merged[-1]
        if start <= previous_end + max_gap:
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return merged


def _is_safe_relative_path(path: str) -> bool:
    """Validate that path is relative and does not escape root lexically."""
    if not is_safe_path(path) or is_rooted_path(path):
        return False
    try:
        norm = PurePosixPath(path.replace("\\", "/"))
        return ".." not in norm.parts and bool(norm.parts)
    except Exception:
        return False


def _is_confined_to_root(resolved_root: Path, path: str) -> bool:
    """Ensure target path resolves strictly within resolved root."""
    if not _is_safe_relative_path(path):
        return False
    try:
        target = (resolved_root / path).resolve(strict=False)
        target.relative_to(resolved_root)
        return True
    except (ValueError, OSError):
        return False


def _read_verified_source(root: Path, relative: str) -> bytes:
    """Open one confined regular-file identity, with a hard byte ceiling."""
    path = root / relative
    # Validate all path components, not just the final name.
    current = root
    for component in PurePosixPath(relative).parts:
        current = current / component
        # Path.is_junction is only available on recent Python versions.
        # Keep the optional Windows check explicitly typed for strict mypy.
        is_junction = cast(Callable[[], bool] | None, getattr(current, "is_junction", None))
        if current.is_symlink() or (is_junction is not None and is_junction()):
            raise PermissionError("evidence path includes a link")
    resolved = path.resolve(strict=True)
    resolved.relative_to(root)
    before = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode):
        raise PermissionError("evidence source is not a regular file")
    if before.st_size > MAX_FILE_BYTES:
        raise ValueError("file_too_large")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode):
            raise PermissionError("evidence source changed type")
        data = stream.read(MAX_FILE_BYTES + 1)
        after = os.fstat(stream.fileno())
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("file_too_large")
    now = path.stat(follow_symlinks=False)
    def identity(item: os.stat_result) -> tuple[int, int, int, int]:
        return (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)

    if identity(before) != identity(opened) or identity(opened) != identity(after) or identity(after) != identity(now):
        raise PermissionError("evidence file changed during read")
    if path.resolve(strict=True) != resolved:
        raise PermissionError("evidence source path changed")
    return data


def merge_overlapping_evidence(
    evidence: list[EvidenceRecord], root: str | Path | None = None
) -> list[EvidenceRecord]:
    """Group evidence by file path and snapshot identity, merging overlapping line ranges."""
    if not evidence:
        return []

    resolved_root: Path | None = None
    if root:
        try:
            resolved_root = Path(root).expanduser().resolve(strict=False)
        except Exception:
            resolved_root = None

    # Group by (path, revision, content_hash, workspace, source_kind)
    # to guarantee content-addressed merging and reject mixing disparate revisions.
    by_key: dict[tuple[str, str, str, str, str], list[EvidenceRecord]] = {}
    group_keys: list[tuple[str, str, str, str, str]] = []

    for item in evidence:
        if not isinstance(item, dict):
            continue
        raw_path = str(item.get("path") or "").strip().replace("\\", "/")
        if not _is_safe_relative_path(raw_path):
            continue
        if resolved_root is not None and not _is_confined_to_root(resolved_root, raw_path):
            continue

        rev = str(item.get("repository_revision") or item.get("revision") or "").strip()
        chash = str(item.get("content_hash") or "").strip()
        ws = str(item.get("workspace") or "").strip()
        source = str(item.get("source_kind") or item.get("source") or "").strip()

        key = (raw_path, rev, chash, ws, source)
        if key not in by_key:
            by_key[key] = []
            group_keys.append(key)
        by_key[key].append(dict(item))

    result: list[EvidenceRecord] = []

    for key in group_keys:
        path, rev, chash, _ws, _source = key
        items = by_key[key]
        if len(items) == 1:
            result.append(items[0])
            continue

        def get_range(item: EvidenceRecord) -> tuple[int, int]:
            start = _safe_line_number(item.get("start_line"), 1)
            end = _safe_line_number(item.get("end_line"), start)
            return (min(start, end), max(start, end))

        sorted_items = sorted(items, key=lambda it: get_range(it))

        clusters: list[tuple[int, int, list[EvidenceRecord]]] = []
        for item in sorted_items:
            item_start, item_end = get_range(item)
            if not clusters:
                clusters.append((item_start, item_end, [item]))
            else:
                c_start, c_end, c_items = clusters[-1]
                if item_start <= c_end + 1:
                    clusters[-1] = (c_start, max(c_end, item_end), c_items)
                    c_items.append(item)
                else:
                    clusters.append((item_start, item_end, [item]))

        for cluster_start, cluster_end, cluster in clusters:
            if len(cluster) == 1:
                result.append(cluster[0])
                continue

            full_end_line = cluster_end
            omitted_lines = max(0, cluster_end - cluster_start + 1 - MAX_MERGED_LINES)
            if omitted_lines:
                cluster_end = cluster_start + MAX_MERGED_LINES - 1

            max_score = max(
                _safe_score(item.get("score"))
                for item in cluster
            )

            symbols = []
            for item in cluster:
                symbol = str(item.get("symbol", "") or "").strip()
                if symbol and symbol not in symbols:
                    symbols.append(symbol)

            merged_symbol = ", ".join(symbols) if symbols else ""

            merged_text = ""
            snapshot_verified = False
            freshness = "unverified"
            fallback_reason = ""
            source_kind = "in_memory_evidence"
            verified_read_at: float | None = None

            file_on_disk = (resolved_root / path) if (resolved_root and _is_confined_to_root(resolved_root, path)) else None
            if resolved_root is not None and file_on_disk is not None and file_on_disk.is_file():
                try:
                    if not chash:
                        # Unhashed evidence remains tied to its own provenance.
                        fallback_reason = "missing_content_hash"
                    else:
                        raw_bytes = _read_verified_source(resolved_root, path)
                        disk_hash = hashlib.sha256(raw_bytes).hexdigest()
                        if disk_hash == chash:
                            all_lines = raw_bytes.decode("utf-8", errors="replace").splitlines()
                            slice_lines = all_lines[max(0, cluster_start - 1):cluster_end]
                            merged_text = "\n".join(slice_lines)
                            snapshot_verified = True
                            freshness = "verified"
                            source_kind = "disk_snapshot"
                            verified_read_at = time.time()
                        else:
                            fallback_reason = "disk_hash_mismatch"
                            freshness = "stale"
                except ValueError as exc:
                    fallback_reason = "file_too_large" if str(exc) == "file_too_large" else "disk_read_failed"
                except (OSError, PermissionError):
                    fallback_reason = "disk_read_failed"

            if not merged_text:
                line_map: dict[int, str] = {}
                for item in cluster:
                    item_start = get_range(item)[0]
                    item_text = str(item.get("text", item.get("content", "")) or "")
                    for index, line in enumerate(item_text.splitlines()):
                        line_number = item_start + index
                        if line_number not in line_map:
                            line_map[line_number] = line
                merged_text = "\n".join(
                    line_map.get(index, "")
                    for index in range(cluster_start, cluster_end + 1)
                )

            best_item = max(
                cluster,
                key=lambda item: _safe_score(item.get("score")),
            )
            merged_item = dict(best_item)
            merged_item["start_line"] = cluster_start
            merged_item["end_line"] = cluster_end
            merged_item["truncated"] = omitted_lines > 0
            merged_item["partial"] = omitted_lines > 0
            merged_item["requested_end_line"] = full_end_line
            merged_item["returned_end_line"] = cluster_end
            merged_item["omitted_lines"] = omitted_lines
            merged_item["original_source_kind"] = _source
            merged_item["revision_verified"] = bool(best_item.get("revision_verified")) and snapshot_verified
            if verified_read_at is not None:
                merged_item["read_at"] = verified_read_at
            if omitted_lines:
                # A recovery descriptor is only emitted when the exact bytes
                # were proven against a full content digest. Every caller must
                # still reauthorize root/path and revalidate content_hash.
                merged_item["slice_recovery"] = ({
                    "path": path,
                    "start_line": cluster_end + 1,
                    "end_line": full_end_line,
                    "content_hash": chash,
                    "repository_revision": rev or None,
                } if snapshot_verified else None)
            if omitted_lines:
                merged_item["original_end_line"] = full_end_line
                merged_item["truncation_reason"] = "max_merged_lines"
            merged_item["score"] = max_score
            merged_item["text"] = merged_text
            merged_item["snapshot_verified"] = snapshot_verified
            merged_item["freshness"] = freshness
            if fallback_reason:
                merged_item["fallback_reason"] = fallback_reason
            merged_item["source_kind"] = source_kind
            if "content" in merged_item:
                merged_item["content"] = merged_text
            if merged_symbol:
                merged_item["symbol"] = merged_symbol

            parent_ids = [str(item["evidence_id"]) for item in cluster if item.get("evidence_id")]
            if parent_ids:
                merged_item["parent_evidence_ids"] = parent_ids
                lineage = "+".join(sorted(parent_ids))
                digest = hashlib.sha256(f"{path}:{cluster_start}:{cluster_end}:{lineage}".encode("utf-8")).hexdigest()[:16]
                merged_item["evidence_id"] = f"merged-{digest}"

            merged_item["merged_from_count"] = len(cluster)
            result.append(merged_item)

    return result
