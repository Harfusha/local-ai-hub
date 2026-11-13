"""Evidence range grouping used by repository service projections."""

from __future__ import annotations

from pathlib import Path
from typing import cast


EvidenceRecord = dict[str, object]


def merge_overlapping_line_ranges(
    ranges: list[tuple[int, int]], *, max_gap: int = 1
) -> list[tuple[int, int]]:
    """Merge overlapping or adjacent line intervals [start, end]."""
    valid = []
    for item in ranges:
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            try:
                start, end = int(item[0]), int(item[1])
                if start > end:
                    start, end = end, start
                valid.append((start, end))
            except (TypeError, ValueError):
                continue
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


def merge_overlapping_evidence(
    evidence: list[EvidenceRecord], root: str | Path | None = None
) -> list[EvidenceRecord]:
    """Group evidence by file path and merge overlapping or adjacent line ranges."""
    if not evidence:
        return []

    by_path: dict[str, list[EvidenceRecord]] = {}
    path_keys: list[str] = []

    for item in evidence:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip().replace("\\", "/")
        if not path:
            continue
        if path not in by_path:
            by_path[path] = []
            path_keys.append(path)
        by_path[path].append(dict(item))

    resolved_root = Path(root).expanduser().resolve(strict=False) if root else None
    result: list[EvidenceRecord] = []

    for path in path_keys:
        items = by_path[path]
        if len(items) == 1:
            result.append(items[0])
            continue

        def get_range(item: EvidenceRecord) -> tuple[int, int]:
            start = int(cast(int | float | str, item.get("start_line", 1) or 1))
            end = int(cast(int | float | str, item.get("end_line", start) or start))
            return (min(start, end), max(start, end))

        sorted_items = sorted(items, key=lambda item: get_range(item))

        clusters: list[list[EvidenceRecord]] = []
        for item in sorted_items:
            item_range = get_range(item)
            if not clusters:
                clusters.append([item])
            else:
                cluster = clusters[-1]
                cluster_end = max(get_range(part)[1] for part in cluster)
                if item_range[0] <= cluster_end + 1:
                    cluster.append(item)
                else:
                    clusters.append([item])

        for cluster in clusters:
            if len(cluster) == 1:
                result.append(cluster[0])
                continue

            cluster_start = min(get_range(item)[0] for item in cluster)
            cluster_end = max(get_range(item)[1] for item in cluster)
            max_score = max(
                float(cast(float | int | str, item.get("score", 0.0) or 0.0))
                for item in cluster
            )

            symbols = []
            for item in cluster:
                symbol = str(item.get("symbol", "") or "").strip()
                if symbol and symbol not in symbols:
                    symbols.append(symbol)

            merged_symbol = ", ".join(symbols) if symbols else ""

            merged_text = ""
            file_on_disk = (resolved_root / path) if resolved_root else None
            if file_on_disk and file_on_disk.is_file():
                try:
                    all_lines = file_on_disk.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()
                    slice_lines = all_lines[max(0, cluster_start - 1) : cluster_end]
                    merged_text = "\n".join(slice_lines)
                except Exception:
                    merged_text = ""

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
                key=lambda item: float(
                    cast(float | int | str, item.get("score", 0.0) or 0.0)
                ),
            )
            merged_item = dict(best_item)
            merged_item["start_line"] = cluster_start
            merged_item["end_line"] = cluster_end
            merged_item["score"] = max_score
            merged_item["text"] = merged_text
            if "content" in merged_item:
                merged_item["content"] = merged_text
            if merged_symbol:
                merged_item["symbol"] = merged_symbol
            result.append(merged_item)

    return result
