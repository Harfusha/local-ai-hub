from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


_TRAIN_ROLES = ("system", "user", "assistant")
_EVAL_ROLES = ("system", "user")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _read_jsonl(path: Path, *, split: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ValueError(f"{split} dataset does not exist: {path}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{split} JSONL line {line_number} is invalid: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{split} JSONL line {line_number} must be an object")
        rows.append(value)
    if not rows:
        raise ValueError(f"{split} dataset is empty")
    return rows


def _validate_row(row: dict[str, Any], *, split: str, line_number: int) -> None:
    prefix = f"{split} JSONL line {line_number}"
    for key in ("id", "group_id"):
        if not isinstance(row.get(key), str) or not row[key].strip():
            raise ValueError(f"{prefix} needs non-empty {key}")
    provenance = row.get("provenance")
    if not isinstance(provenance, dict) or not provenance:
        raise ValueError(f"{prefix} needs non-empty provenance")
    source_hash = row.get("source_sha256", provenance.get("source_sha256"))
    if source_hash is not None and (not isinstance(source_hash, str) or not _SHA256_RE.fullmatch(source_hash)):
        raise ValueError(f"{prefix} source_sha256 must be a 64-character hexadecimal digest")
    messages = row.get("messages")
    expected_roles = _TRAIN_ROLES if split == "train" else _EVAL_ROLES
    if not isinstance(messages, list) or tuple(
        message.get("role") if isinstance(message, dict) else None for message in messages
    ) != expected_roles:
        raise ValueError(f"{prefix} messages must have roles {', '.join(expected_roles)}")
    for message in messages:
        if not isinstance(message.get("content"), str) or not message["content"].strip():
            raise ValueError(f"{prefix} messages need non-empty string content")
    if split == "evaluation" and not any(key in row for key in ("expected", "required_facts", "forbidden_claims")):
        raise ValueError(f"{prefix} needs expected output or task-specific scoring criteria")


def validate_dataset_pair(train_path: Path | str, evaluation_path: Path | str) -> dict[str, Any]:
    """Validate chat JSONL inputs and reject project/content leakage across splits."""
    train_file, eval_file = Path(train_path), Path(evaluation_path)
    train_rows = _read_jsonl(train_file, split="train")
    eval_rows = _read_jsonl(eval_file, split="evaluation")

    for split, rows in (("train", train_rows), ("evaluation", eval_rows)):
        seen: set[str] = set()
        for line_number, row in enumerate(rows, 1):
            _validate_row(row, split=split, line_number=line_number)
            item_id = row["id"]
            if item_id in seen:
                raise ValueError(f"duplicate id in {split} dataset: {item_id}")
            seen.add(item_id)

    train_ids = {row["id"] for row in train_rows}
    eval_ids = {row["id"] for row in eval_rows}
    if train_ids & eval_ids:
        raise ValueError("duplicate id across train/evaluation datasets")
    group_overlap = sorted({row["group_id"] for row in train_rows} & {row["group_id"] for row in eval_rows})
    if group_overlap:
        raise ValueError(f"group leakage across train/evaluation datasets: {group_overlap[:5]}")
    train_hashes = {
        row.get("source_sha256", row["provenance"].get("source_sha256"))
        for row in train_rows
        if row.get("source_sha256", row["provenance"].get("source_sha256")) is not None
    }
    eval_hashes = {
        row.get("source_sha256", row["provenance"].get("source_sha256"))
        for row in eval_rows
        if row.get("source_sha256", row["provenance"].get("source_sha256")) is not None
    }
    hash_overlap = sorted(train_hashes & eval_hashes)
    if hash_overlap:
        raise ValueError(f"source hash leakage across train/evaluation datasets: {hash_overlap[:5]}")

    return {
        "train_rows": len(train_rows),
        "evaluation_rows": len(eval_rows),
        "train_groups": len({row["group_id"] for row in train_rows}),
        "evaluation_groups": len({row["group_id"] for row in eval_rows}),
        "group_overlap": [],
        "source_hash_overlap": [],
    }


def load_run_manifest(path: Path | str) -> dict[str, Any]:
    """Load and validate one explicit model-training run manifest."""
    manifest_path = Path(path).resolve()
    try:
        config = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read run manifest: {exc}") from exc
    if not isinstance(config, dict):
        raise ValueError("run manifest must be a JSON object")
    required = ("schema_version", "name", "task_type", "base_model", "train_file", "evaluation_file", "output_dir", "system_prompt", "output_schema")
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"run manifest missing fields: {', '.join(missing)}")
    if config["schema_version"] != 1:
        raise ValueError("unsupported run manifest schema_version")
    if config["task_type"] not in {"preprocess_card", "decision_model"}:
        raise ValueError("task_type must be preprocess_card or decision_model")
    for key in ("name", "base_model", "system_prompt"):
        if not isinstance(config[key], str) or not config[key].strip():
            raise ValueError(f"run manifest {key} must be a non-empty string")
    if not isinstance(config["output_schema"], dict):
        raise ValueError("run manifest output_schema must be a JSON Schema object")
    try:
        Draft202012Validator.check_schema(config["output_schema"])
    except Exception as exc:
        raise ValueError(f"run manifest output_schema is invalid: {exc}") from exc

    config["_manifest_path"] = str(manifest_path)
    for key in ("train_file", "evaluation_file", "output_dir"):
        value = Path(config[key])
        config[key] = str(value if value.is_absolute() else (manifest_path.parent / value).resolve())
    return config
