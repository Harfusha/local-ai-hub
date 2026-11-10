from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .manifest import _read_jsonl, _validate_row, validate_dataset_pair


def _write_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def split_dataset(
    source_path: Path | str,
    train_path: Path | str,
    evaluation_path: Path | str,
    *,
    evaluation_fraction: float = 0.2,
    seed: int = 20261110,
) -> dict[str, Any]:
    """Create deterministic group-held-out JSONL; duplicate source hashes stay together."""
    if not 0.05 <= evaluation_fraction <= 0.5:
        raise ValueError("evaluation_fraction must be between 0.05 and 0.5")
    source_file = Path(source_path).resolve()
    train_output, eval_output = Path(train_path).resolve(), Path(evaluation_path).resolve()
    if source_file in {train_output, eval_output} or train_output == eval_output:
        raise ValueError("source, train, and evaluation paths must be distinct")
    rows = _read_jsonl(source_file, split="source")
    group_values = [row.get("group_id") for row in rows]
    if any(not isinstance(group, str) or not group for group in group_values):
        raise ValueError("every source row needs a non-empty group_id")
    groups = set(group_values)
    for line_number, row in enumerate(rows, 1):
        _validate_row(row, split="train", line_number=line_number)
    ids = [row.get("id") for row in rows]
    if any(not isinstance(item_id, str) or not item_id for item_id in ids) or len(set(ids)) != len(ids):
        raise ValueError("source rows need unique non-empty ids")

    parent = {group: group for group in groups}

    def find(group: str) -> str:
        while parent[group] != group:
            parent[group] = parent[parent[group]]
            group = parent[group]
        return group

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    owner_by_hash: dict[str, str] = {}
    for row in rows:
        provenance = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
        digest = row.get("source_sha256", provenance.get("source_sha256"))
        if isinstance(digest, str) and digest:
            previous_group = owner_by_hash.setdefault(digest, row["group_id"])
            union(previous_group, row["group_id"])

    components: dict[str, set[str]] = {}
    for group in groups:
        components.setdefault(find(group), set()).add(group)
    if len(components) < 2:
        raise ValueError("at least two independent groups are required for a held-out split")
    rows_by_component: dict[str, int] = {key: 0 for key in components}
    for row in rows:
        rows_by_component[find(row["group_id"])] += 1
    ordered_components = sorted(
        components,
        key=lambda key: hashlib.sha256(f"{seed}\0{'|'.join(sorted(components[key]))}".encode()).hexdigest(),
    )
    target_rows = max(1, round(len(rows) * evaluation_fraction))
    evaluation_components: set[str] = set()
    evaluation_rows_count = 0
    for component in ordered_components[:-1]:
        if not evaluation_components or evaluation_rows_count < target_rows:
            evaluation_components.add(component)
            evaluation_rows_count += rows_by_component[component]
    evaluation_groups = {group for key in evaluation_components for group in components[key]}
    train_rows: list[dict[str, Any]] = []
    eval_rows: list[dict[str, Any]] = []
    for row in rows:
        if row["group_id"] not in evaluation_groups:
            train_rows.append(row)
            continue
        eval_row = dict(row)
        eval_row["messages"] = row["messages"][:2]
        answer = row["messages"][2]["content"]
        try:
            eval_row["expected"] = json.loads(answer)
        except (TypeError, json.JSONDecodeError):
            eval_row["expected"] = answer
        eval_rows.append(eval_row)

    _write_jsonl_atomic(train_output, train_rows)
    _write_jsonl_atomic(eval_output, eval_rows)
    validated = validate_dataset_pair(train_output, eval_output)
    return {
        **validated,
        "seed": seed,
        "evaluation_fraction_requested": evaluation_fraction,
        "evaluation_fraction_actual": round(len(eval_rows) / len(rows), 4),
        "evaluation_group_ids": sorted(evaluation_groups),
    }
