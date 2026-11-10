from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
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


def split_embedding_corpus(
    source_path: Path | str,
    train_path: Path | str,
    evaluation_path: Path | str,
    *,
    evaluation_fraction: float = 0.2,
    seed: int = 20261110,
) -> dict[str, Any]:
    """Deduplicate exact card text, then split the remaining corpus by project."""
    if not 0.05 <= evaluation_fraction <= 0.5:
        raise ValueError("evaluation_fraction must be between 0.05 and 0.5")
    source_file = Path(source_path).resolve()
    train_output, eval_output = Path(train_path).resolve(), Path(evaluation_path).resolve()
    if source_file in {train_output, eval_output} or train_output == eval_output:
        raise ValueError("source, train, and evaluation paths must be distinct")
    rows = _read_jsonl(source_file, split="embedding corpus")
    groups: set[str] = set()
    ids: set[str] = set()
    rows_by_hash: dict[str, dict[str, Any]] = {}

    for line_number, row in enumerate(rows, 1):
        group, row_id = row.get("group_id"), row.get("id")
        if not isinstance(group, str) or not group.strip():
            raise ValueError(f"embedding corpus line {line_number} needs group_id")
        if not isinstance(row_id, str) or not row_id.strip() or row_id in ids:
            raise ValueError(f"embedding corpus line {line_number} needs a unique id")
        if not isinstance(row.get("text"), str) or not row["text"].strip():
            raise ValueError(f"embedding corpus line {line_number} needs non-empty text")
        provenance = row.get("provenance")
        digest = provenance.get("card_sha256") if isinstance(provenance, dict) else None
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"embedding corpus line {line_number} needs provenance.card_sha256")
        ids.add(row_id)
        groups.add(group)
        previous = rows_by_hash.get(digest)
        if previous is None or (group, row_id) < (previous["group_id"], previous["id"]):
            rows_by_hash[digest] = row

    deduplicated_rows = [rows_by_hash[key] for key in sorted(rows_by_hash)]
    deduplicated_groups = {row["group_id"] for row in deduplicated_rows}
    if len(deduplicated_groups) < 2:
        raise ValueError("at least two independent project groups are required for a held-out split")
    rows_by_group = {group: 0 for group in deduplicated_groups}
    for row in deduplicated_rows:
        rows_by_group[row["group_id"]] += 1
    ordered = sorted(
        deduplicated_groups,
        key=lambda group: hashlib.sha256(f"{seed}\0{group}".encode()).hexdigest(),
    )
    target = max(1, round(len(deduplicated_rows) * evaluation_fraction))
    evaluation_groups: set[str] = set()
    evaluation_count = 0
    for group in ordered[:-1]:
        if not evaluation_groups or evaluation_count < target:
            evaluation_groups.add(group)
            evaluation_count += rows_by_group[group]
    train_rows = [row for row in deduplicated_rows if row["group_id"] not in evaluation_groups]
    eval_rows = [row for row in deduplicated_rows if row["group_id"] in evaluation_groups]
    if not train_rows or not eval_rows:
        raise ValueError("project-group split did not produce non-empty train and evaluation sets")
    train_hashes = {row["provenance"]["card_sha256"] for row in train_rows}
    eval_hashes = {row["provenance"]["card_sha256"] for row in eval_rows}
    if train_hashes & eval_hashes:
        raise ValueError("identical existing card content leaked across embedding splits")
    _write_jsonl_atomic(train_output, train_rows)
    _write_jsonl_atomic(eval_output, eval_rows)
    return {
        "success": True,
        "format": "embedding-corpus",
        "source_count": len(rows),
        "deduplicated_count": len(deduplicated_rows),
        "exact_duplicate_rows_removed": len(rows) - len(deduplicated_rows),
        "train_count": len(train_rows),
        "evaluation_count": len(eval_rows),
        "project_group_count": len(deduplicated_groups),
        "evaluation_group_ids": sorted(evaluation_groups),
        "seed": seed,
        "evaluation_fraction_requested": evaluation_fraction,
        "evaluation_fraction_actual": round(len(eval_rows) / len(deduplicated_rows), 4),
        "relevance_labels": "not_present",
    }
