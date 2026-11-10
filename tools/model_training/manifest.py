from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def validate_run_options(training: Any, benchmark: Any, lora: Any) -> None:
    if not isinstance(training, dict) or not isinstance(benchmark, dict) or not isinstance(lora, dict):
        raise ValueError("training, benchmark, and lora options must be JSON objects")
    device = training.get("device", "cuda")
    quantization = training.get("quantization", "none")
    if not isinstance(device, str) or device not in {"cuda", "cpu"}:
        raise ValueError("training.device must be cuda or cpu")
    if not isinstance(quantization, str) or quantization not in {"none", "4bit"}:
        raise ValueError("training.quantization must be none or 4bit")
    if quantization == "4bit" and device != "cuda":
        raise ValueError("4bit QLoRA requires training.device=cuda")
    bounds = {
        "epochs": (1, 20),
        "batch_size": (1, 32),
        "gradient_accumulation_steps": (1, 128),
        "max_length": (16, 32768),
    }
    for name, (minimum, maximum) in bounds.items():
        value = training.get(name)
        if value is not None and (type(value) is not int or not minimum <= value <= maximum):
            raise ValueError(f"training.{name} must be an integer from {minimum} to {maximum}")
    learning_rate = training.get("learning_rate", 2e-4)
    if isinstance(learning_rate, bool) or not isinstance(learning_rate, (int, float)) or not math.isfinite(learning_rate) or learning_rate <= 0:
        raise ValueError("training.learning_rate must be a finite positive number")
    attention = training.get("attention", "sdpa")
    if not isinstance(attention, str) or attention not in {"sdpa", "eager"}:
        raise ValueError("training.attention must be sdpa or eager")
    gradient_checkpointing = training.get("gradient_checkpointing", True)
    if not isinstance(gradient_checkpointing, bool):
        raise ValueError("training.gradient_checkpointing must be boolean")
    max_grad_norm = training.get("max_grad_norm", 1.0)
    if isinstance(max_grad_norm, bool) or not isinstance(max_grad_norm, (int, float)) or not math.isfinite(max_grad_norm) or max_grad_norm <= 0:
        raise ValueError("training.max_grad_norm must be a finite positive number")
    for name, minimum, maximum in (("r", 1, 256), ("alpha", 1, 1024)):
        value = lora.get(name)
        if value is not None and (type(value) is not int or not minimum <= value <= maximum):
            raise ValueError(f"lora.{name} must be an integer from {minimum} to {maximum}")
    dropout = lora.get("dropout", 0.05)
    if isinstance(dropout, bool) or not isinstance(dropout, (int, float)) or not 0 <= dropout < 1:
        raise ValueError("lora.dropout must be in [0, 1)")
    target_modules = lora.get("target_modules", ["q_proj", "k_proj", "v_proj", "o_proj"])
    if not isinstance(target_modules, list) or not target_modules or any(not isinstance(item, str) or not item for item in target_modules):
        raise ValueError("lora.target_modules must be a non-empty list of strings")
    benchmark_device = benchmark.get("device", device)
    if not isinstance(benchmark_device, str) or benchmark_device not in {"cuda", "cpu"}:
        raise ValueError("benchmark.device must be cuda or cpu")
    for name, minimum, maximum in (("max_new_tokens", 1, 8192), ("warmup_runs", 0, 5)):
        value = benchmark.get(name)
        if value is not None and (type(value) is not int or not minimum <= value <= maximum):
            raise ValueError(f"benchmark.{name} must be an integer from {minimum} to {maximum}")
    if quantization == "4bit" and benchmark_device != "cuda":
        raise ValueError("4bit QLoRA requires benchmark.device=cuda")


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
    if not isinstance(messages, list) or len(messages) < 2:
        raise ValueError(f"{prefix} messages must be a non-empty chat")
    roles = tuple(message.get("role") if isinstance(message, dict) else None for message in messages)
    valid = (
        split == "train"
        and len(roles) >= 3
        and roles[0] == "system"
        and roles[-2:] == ("user", "assistant")
        or split != "train"
        and len(roles) >= 2
        and roles[0] == "system"
        and roles[-1] == "user"
    )
    if not valid or any(role not in {"system", "user", "assistant"} for role in roles):
        expected = "system … user, assistant" if split == "train" else "system … user"
        raise ValueError(f"{prefix} messages must end with roles {expected}")
    for message in messages:
        if not isinstance(message.get("content"), str) or not message["content"].strip():
            raise ValueError(f"{prefix} messages need non-empty string content")
    if split == "evaluation" and not any(key in row for key in ("expected", "required_facts", "forbidden_claims")):
        raise ValueError(f"{prefix} needs expected output or task-specific scoring criteria")


def validate_dataset_pair(
    train_path: Path | str,
    evaluation_path: Path | str,
    *,
    backend: str = "transformers_lora",
) -> dict[str, Any]:
    """Validate chat JSONL inputs and reject project/content leakage across splits."""
    if backend == "laya":
        from .laya_backend import validate_laya_dataset_pair

        return validate_laya_dataset_pair(train_path, evaluation_path)
    if backend != "transformers_lora":
        raise ValueError(f"unsupported model-training backend: {backend}")
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
    backend = config.get("backend", "transformers_lora")
    if backend == "laya":
        from .laya_backend import load_laya_run_manifest

        return load_laya_run_manifest(manifest_path)
    if backend != "transformers_lora":
        raise ValueError(f"unsupported model-training backend: {backend}")
    required = ("schema_version", "name", "task_type", "base_model", "train_file", "evaluation_file", "output_dir", "system_prompt", "output_schema")
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"run manifest missing fields: {', '.join(missing)}")
    if config["schema_version"] != 1:
        raise ValueError("unsupported run manifest schema_version")
    if not isinstance(config["task_type"], str) or config["task_type"] not in {"preprocess_card", "decision_model"}:
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
    validate_run_options(config.get("training", {}), config.get("benchmark", {}), config.get("lora", {}))

    config["_manifest_path"] = str(manifest_path)
    config["backend"] = backend
    for key in ("train_file", "evaluation_file", "output_dir"):
        if not isinstance(config[key], str) or not config[key].strip():
            raise ValueError(f"run manifest {key} must be a non-empty path string")
        value = Path(config[key])
        config[key] = str(value if value.is_absolute() else (manifest_path.parent / value).resolve())
    return config
