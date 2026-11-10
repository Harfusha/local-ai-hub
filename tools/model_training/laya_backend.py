"""Laya typed-decision training backend for the shared model-training scaffold.

This backend delegates the model-specific objective, calibration and checkpoint
layout to the pinned upstream Laya API. It never runs as part of Hub startup.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_RUN_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_TRAINING_FIELDS = {
    "device", "epochs", "micro_batch", "grad_accum", "encoder_lr", "head_lr",
    "min_lr", "weight_decay", "grad_clip", "loss", "rl_samples", "sigma_start",
    "sigma_end", "w_sph", "w_rps", "shuffle_options", "option_layout",
    "freeze_encoder", "calib_max", "calib_frac", "calib_seed", "seed", "max_len",
    "head_max_len", "amp", "gradient_checkpointing", "log_every", "label_smoothing",
    "text_column", "label_column", "question_id", "instructions", "eval_data",
    "target_error", "min_abstain_n",
}
_BENCHMARK_FIELDS = {"device", "backend", "batch_size", "sort_by_length"}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _directory_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    entries = list(path.rglob("*"))
    if any(item.is_symlink() and item.resolve(strict=True).is_dir() for item in entries):
        raise ValueError(f"checkpoint contains a directory symlink: {path}")
    files = sorted(item for item in entries if item.is_file())
    for item in files:
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(bytes.fromhex(_file_sha256(item)))
    if not files:
        raise ValueError(f"checkpoint directory is empty: {path}")
    return digest.hexdigest()


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def validate_laya_training_options(training: Any, benchmark: Any) -> None:
    if not isinstance(training, dict) or not isinstance(benchmark, dict):
        raise ValueError("Laya training and benchmark settings must be JSON objects")
    unknown_training = sorted(set(training) - _TRAINING_FIELDS)
    if unknown_training:
        raise ValueError(f"unknown Laya training setting(s): {', '.join(unknown_training)}")
    unknown_benchmark = sorted(set(benchmark) - _BENCHMARK_FIELDS)
    if unknown_benchmark:
        raise ValueError(f"unknown Laya benchmark setting(s): {', '.join(unknown_benchmark)}")

    for settings, label in ((training, "training"), (benchmark, "benchmark")):
        device = settings.get("device", "cuda")
        if not isinstance(device, str) or device not in {"cuda", "cpu"}:
            raise ValueError(f"{label}.device must be cuda or cpu")
    loss = training.get("loss", "rlcd")
    if not isinstance(loss, str) or loss not in {"rlcd", "soft-ce"}:
        raise ValueError("training.loss must be rlcd or soft-ce")
    option_layout = training.get("option_layout")
    if option_layout is not None and (not isinstance(option_layout, str)
                                      or option_layout not in {"sequential", "parallel"}):
        raise ValueError("training.option_layout must be sequential, parallel, or null")
    if not isinstance(training.get("freeze_encoder", False), bool):
        raise ValueError("training.freeze_encoder must be boolean")
    for name, low, high in (("epochs", 1, 128), ("micro_batch", 1, 256),
                            ("grad_accum", 1, 1024), ("rl_samples", 1, 64),
                            ("calib_max", 0, 100000), ("calib_seed", 0, 2**31 - 1),
                            ("seed", 0, 2**31 - 1), ("max_len", 16, 32768),
                            ("head_max_len", 8, 8192), ("log_every", 1, 100000),
                            ("min_abstain_n", 0, 100000)):
        value = training.get(name)
        if value is not None and (type(value) is not int or not low <= value <= high):
            raise ValueError(f"training.{name} must be an integer from {low} to {high}")
    for name, default, low, high, inclusive_high in (
        ("encoder_lr", 2.5e-5, 0.0, 1.0, False),
        ("head_lr", 1e-4, 0.0, 1.0, False),
        ("min_lr", 1e-6, 0.0, 1.0, False),
        ("weight_decay", 0.01, 0.0, 10.0, True),
        ("grad_clip", 1.0, 0.0, 100.0, False),
        ("sigma_start", 0.4, 0.0, 10.0, True),
        ("sigma_end", 0.1, 0.0, 10.0, True),
        ("w_sph", 0.75, 0.0, 100.0, True),
        ("w_rps", 1.0, 0.0, 100.0, True),
        ("calib_frac", 0.1, 0.0, 1.0, False),
        ("label_smoothing", 0.0, 0.0, 1.0, False),
        ("target_error", 0.1, 0.0, 1.0, True),
    ):
        value = training.get(name, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"training.{name} must be a finite number")
        if value < low or (value > high if inclusive_high else value >= high):
            edge = "]" if inclusive_high else ")"
            raise ValueError(f"training.{name} must be in [{low}, {high}{edge}")
    for name in ("amp", "gradient_checkpointing"):
        value = training.get(name)
        if value is not None and not isinstance(value, bool):
            raise ValueError(f"training.{name} must be boolean")
    shuffle = training.get("shuffle_options", [])
    if not isinstance(shuffle, list) or any(not isinstance(item, str)
                                            or item not in {"choice", "score", "noul"} for item in shuffle):
        raise ValueError("training.shuffle_options must list choice, score, or noul")
    for name in ("text_column", "label_column", "question_id", "instructions"):
        value = training.get(name)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"training.{name} must be a string")

    backend = benchmark.get("backend", "auto")
    if not isinstance(backend, str) or backend not in {"auto", "eager", "compile", "tilelang"}:
        raise ValueError("benchmark.backend must be auto, eager, compile, or tilelang")
    batch_size = benchmark.get("batch_size", 1)
    if type(batch_size) is not int or not 1 <= batch_size <= 1024:
        raise ValueError("benchmark.batch_size must be an integer from 1 to 1024")
    sort_by_length = benchmark.get("sort_by_length", False)
    if not isinstance(sort_by_length, bool):
        raise ValueError("benchmark.sort_by_length must be boolean")


def _resolve_manifest(path: Path | str, *, matrix: bool) -> dict[str, Any]:
    manifest_path = Path(path).resolve()
    try:
        config = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read Laya manifest: {exc}") from exc
    if not isinstance(config, dict):
        raise ValueError("Laya manifest must be a JSON object")
    expected = ("schema_version", "name", "backend", "task_type", "base_model", "base_revision",
                "train_file", "evaluation_file", "output_root" if matrix else "output_dir")
    missing = [key for key in expected if key not in config]
    if missing:
        raise ValueError(f"Laya manifest missing fields: {', '.join(missing)}")
    if config["schema_version"] != 1 or config["backend"] != "laya" or config["task_type"] != "decision_model":
        raise ValueError("Laya manifests need schema_version=1, backend=laya, task_type=decision_model")
    if not isinstance(config["name"], str) or not _RUN_NAME_RE.fullmatch(config["name"]):
        raise ValueError("Laya manifest name must be a safe non-empty run name")
    if not isinstance(config["base_model"], str) or not config["base_model"].strip():
        raise ValueError("base_model must be a non-empty local path or Hub repository ID")
    revision = config["base_revision"]
    if not isinstance(revision, str) or not _REVISION_RE.fullmatch(revision):
        raise ValueError("base_revision must be a pinned 40-character lowercase commit SHA")

    config["training"] = dict(config.get("training", {}))
    config["benchmark"] = dict(config.get("benchmark", {}))
    validate_laya_training_options(config["training"], config["benchmark"])
    config["_manifest_path"] = str(manifest_path)
    for key in ("train_file", "evaluation_file", "output_root" if matrix else "output_dir"):
        value = config[key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Laya manifest {key} must be a non-empty path string")
        path_value = Path(value)
        config[key] = str(path_value if path_value.is_absolute() else (manifest_path.parent / path_value).resolve())
    base_text = config["base_model"]
    base = Path(base_text)
    looks_like_path = base.is_absolute() or base_text.startswith((".", "~")) or base.exists()
    if looks_like_path:
        if not base.is_absolute():
            base = (manifest_path.parent / base).resolve()
        config["base_model"] = str(base)
    return config


def load_laya_matrix_manifest(path: Path | str) -> dict[str, Any]:
    return _resolve_manifest(path, matrix=True)


def load_laya_run_manifest(path: Path | str) -> dict[str, Any]:
    return _resolve_manifest(path, matrix=False)


def _read_laya_rows(path: Path | str, *, split: str) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"{split} Laya dataset does not exist: {source}")
    rows: list[dict[str, Any]] = []
    try:
        with source.open("r", encoding="utf-8-sig") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{source}:{line_number}: invalid JSON: {exc.msg}") from exc
                _validate_laya_row(row, source=source, line_number=line_number)
                rows.append(row)
    except UnicodeError as exc:
        raise ValueError(f"{source}: dataset is not valid UTF-8") from exc
    if not rows:
        raise ValueError(f"{split} Laya dataset is empty: {source}")
    return rows


def _opaque_id(value: Any, *, field: str, label: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value):
        raise ValueError(f"{label}: {field} must be a non-empty opaque receipt ID")


def _validate_laya_label_provenance(
    provenance: Any,
    targets: dict[str, Any],
    *,
    label: str,
) -> None:
    if not isinstance(provenance, dict):
        raise ValueError(f"{label}: verified label provenance is required")
    data_class = provenance.get("data_class")
    if data_class == "synthetic_non_private":
        _opaque_id(provenance.get("fixture_id"), field="fixture_id", label=label)
    elif data_class == "local_scoped":
        if {"consent", "consent_receipt_id", "per_example_consented", "consent_receipt_sha256"}.intersection(provenance):
            raise ValueError(f"{label}: retired consent fields are not accepted in training provenance")
        candidate_id = provenance.get("candidate_id")
        candidate_hash = provenance.get("candidate_sha256")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise ValueError(f"{label}: Laya candidate provenance needs candidate_id")
        if not isinstance(candidate_hash, str) or not _SHA256_RE.fullmatch(candidate_hash):
            raise ValueError(f"{label}: Laya candidate provenance needs candidate_sha256")
    else:
        raise ValueError(f"{label}: provenance.data_class must be local_scoped or synthetic_non_private")

    proof = provenance.get("label_provenance")
    if not isinstance(proof, dict) or proof.get("status") != "verified":
        raise ValueError(f"{label}: label_provenance.status must be verified")
    target_sha256 = hashlib.sha256(_canonical(targets)).hexdigest()
    if proof.get("target_sha256") != target_sha256:
        raise ValueError(f"{label}: label_provenance.target_sha256 does not match target labels")

    method = proof.get("method")
    if method == "blind_double_annotation":
        annotations = proof.get("annotation_identity_sha256")
        if (not isinstance(annotations, list) or len(annotations) != 2
                or any(not isinstance(item, str) or not _SHA256_RE.fullmatch(item) for item in annotations)
                or len(set(annotations)) != 2):
            raise ValueError(f"{label}: blind_double_annotation needs two distinct annotator identity hashes")
        agreement = proof.get("agreement")
        if not isinstance(agreement, bool):
            raise ValueError(f"{label}: annotation agreement must be boolean")
        adjudicator = proof.get("adjudicator_identity_sha256")
        verifier = proof.get("verification_identity_sha256")
        reviewers = set(annotations)
        if not isinstance(adjudicator, str) or not _SHA256_RE.fullmatch(adjudicator) or adjudicator in reviewers:
            raise ValueError(f"{label}: adjudicator must be independent of both annotators")
        if not isinstance(verifier, str) or not _SHA256_RE.fullmatch(verifier) or verifier in reviewers | {adjudicator}:
            raise ValueError(f"{label}: verification reviewer must be independent")
    elif method == "deterministic_evidence":
        evidence_ids = proof.get("evidence_ids")
        if (not isinstance(evidence_ids, list) or not evidence_ids
                or any(not isinstance(item, str) or not item.strip() for item in evidence_ids)
                or len(set(evidence_ids)) != len(evidence_ids)):
            raise ValueError(f"{label}: deterministic_evidence needs unique evidence IDs")
    elif method == "synthetic_fixture_oracle":
        if data_class != "synthetic_non_private":
            raise ValueError(f"{label}: fixture oracle labels require synthetic_non_private data")
    else:
        raise ValueError(f"{label}: unsupported verified label provenance method")


def _validate_laya_row(row: Any, *, source: Path, line_number: int) -> None:
    label = f"{source}:{line_number}"
    if not isinstance(row, dict):
        raise ValueError(f"{label}: row must be a JSON object")
    for key in ("id", "group_id"):
        if not isinstance(row.get(key), str) or not row[key].strip():
            raise ValueError(f"{label}: {key} must be a non-empty string")
    state = row.get("state")
    if state is None or (isinstance(state, str) and not state.strip()):
        raise ValueError(f"{label}: state must not be empty")
    questions = row.get("questions")
    if not isinstance(questions, dict) or not questions:
        raise ValueError(f"{label}: questions must be a non-empty object")
    if any(not isinstance(qid, str) or not qid.strip() or not isinstance(question, dict)
           for qid, question in questions.items()):
        raise ValueError(f"{label}: questions must map non-empty IDs to objects")
    expected, gold = row.get("expected"), row.get("gold")
    if (expected is None) == (gold is None):
        raise ValueError(f"{label}: provide exactly one of expected or gold")
    targets = expected if expected is not None else gold
    if not isinstance(targets, dict) or not targets or set(targets) - set(questions):
        raise ValueError(f"{label}: labels must map known question IDs to answers")
    if "source_sha256" in row and (not isinstance(row["source_sha256"], str)
                                    or not _SHA256_RE.fullmatch(row["source_sha256"])):
        raise ValueError(f"{label}: source_sha256 must be a 64-character lowercase SHA-256")
    _validate_laya_label_provenance(row.get("provenance"), targets, label=label)
    provenance = row["provenance"]
    if provenance.get("data_class") == "local_scoped":
        if provenance.get("candidate_id") != row["id"]:
            raise ValueError(f"{label}: candidate_id does not match row id")
        if provenance.get("candidate_sha256") != row.get("source_sha256"):
            raise ValueError(f"{label}: candidate_sha256 does not match source_sha256")
    if len(_canonical(row)) > 128 * 1024:
        raise ValueError(f"{label}: row exceeds the 128 KiB safety limit")


def _row_fingerprint(row: dict[str, Any]) -> str:
    digest = row.get("source_sha256")
    provenance = row.get("provenance")
    if digest is None and isinstance(provenance, dict):
        digest = provenance.get("source_sha256")
    if digest is not None:
        return str(digest)
    return hashlib.sha256(_canonical({"state": row["state"], "questions": row["questions"]})).hexdigest()


def validate_laya_dataset_pair(train_path: Path | str, evaluation_path: Path | str) -> dict[str, Any]:
    train_rows = _read_laya_rows(train_path, split="train")
    evaluation_rows = _read_laya_rows(evaluation_path, split="evaluation")
    ids = [row["id"] for row in train_rows + evaluation_rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate Laya dataset ID within or across train/evaluation splits")
    train_groups = {row["group_id"] for row in train_rows}
    eval_groups = {row["group_id"] for row in evaluation_rows}
    overlap = sorted(train_groups & eval_groups)
    if overlap:
        raise ValueError(f"Laya group leakage across train/evaluation datasets: {overlap[:5]}")
    train_hashes = {_row_fingerprint(row) for row in train_rows}
    eval_hashes = {_row_fingerprint(row) for row in evaluation_rows}
    if train_hashes & eval_hashes:
        raise ValueError("Laya exact-state or source-hash leakage across train/evaluation datasets")
    return {
        "train_rows": len(train_rows),
        "evaluation_rows": len(evaluation_rows),
        "train_groups": len(train_groups),
        "evaluation_groups": len(eval_groups),
        "group_overlap": [],
        "source_hash_overlap": [],
    }


def split_laya_dataset(
    source_path: Path | str,
    train_path: Path | str,
    evaluation_path: Path | str,
    *,
    evaluation_fraction: float = 0.2,
    seed: int = 20261110,
) -> dict[str, Any]:
    if not 0.05 <= evaluation_fraction <= 0.5:
        raise ValueError("evaluation_fraction must be between 0.05 and 0.5")
    source_file = Path(source_path).resolve()
    train_output = Path(train_path).resolve()
    evaluation_output = Path(evaluation_path).resolve()
    if source_file in {train_output, evaluation_output} or train_output == evaluation_output:
        raise ValueError("source, train, and evaluation paths must be distinct")
    rows = _read_laya_rows(source_file, split="source")
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("source Laya rows need unique IDs")

    groups = {row["group_id"] for row in rows}
    if len(groups) < 2:
        raise ValueError("at least two independent Laya groups are required for a held-out split")
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

    owner_by_fingerprint: dict[str, str] = {}
    for row in rows:
        fingerprint = _row_fingerprint(row)
        earlier = owner_by_fingerprint.setdefault(fingerprint, row["group_id"])
        union(earlier, row["group_id"])
    components: dict[str, set[str]] = {}
    for group in groups:
        components.setdefault(find(group), set()).add(group)
    if len(components) < 2:
        raise ValueError("duplicate/source-hash links leave fewer than two independent Laya groups")
    sizes = {key: 0 for key in components}
    for row in rows:
        sizes[find(row["group_id"])] += 1
    ordered = sorted(components, key=lambda key: hashlib.sha256(
        f"{seed}\0{'|'.join(sorted(components[key]))}".encode("utf-8")).hexdigest())
    target = max(1, round(len(rows) * evaluation_fraction))
    evaluation_components: set[str] = set()
    evaluation_count = 0
    for component in ordered[:-1]:
        if not evaluation_components or evaluation_count < target:
            evaluation_components.add(component)
            evaluation_count += sizes[component]
    evaluation_groups = {group for key in evaluation_components for group in components[key]}
    train_rows = [row for row in rows if row["group_id"] not in evaluation_groups]
    evaluation_rows = [row for row in rows if row["group_id"] in evaluation_groups]
    from .dataset import _write_jsonl_atomic
    _write_jsonl_atomic(train_output, train_rows)
    _write_jsonl_atomic(evaluation_output, evaluation_rows)
    summary = validate_laya_dataset_pair(train_output, evaluation_output)
    return {
        **summary,
        "seed": seed,
        "evaluation_fraction_requested": evaluation_fraction,
        "evaluation_fraction_actual": round(len(evaluation_rows) / len(rows), 4),
        "evaluation_group_ids": sorted(evaluation_groups),
    }


def _resolve_base_checkpoint(config: dict[str, Any], *, allow_model_download: bool) -> Path:
    base = Path(config["base_model"])
    if base.is_absolute() and not base.is_dir():
        raise ValueError(f"configured local Laya base checkpoint does not exist: {base}")
    if base.is_dir():
        checkpoint = base.resolve()
        if checkpoint.name != config["base_revision"]:
            raise ValueError("local base_model directory name must match the pinned base_revision SHA")
    else:
        if not allow_model_download:
            try:
                from huggingface_hub import snapshot_download
            except ImportError as exc:
                raise RuntimeError("Laya backend needs huggingface_hub; install requirements-laya.txt") from exc
            checkpoint = Path(snapshot_download(
                repo_id=config["base_model"], revision=config["base_revision"],
                local_files_only=True, etag_timeout=10, max_workers=4,
            )).resolve()
        else:
            try:
                from huggingface_hub import snapshot_download
            except ImportError as exc:
                raise RuntimeError("Laya backend needs huggingface_hub; install requirements-laya.txt") from exc
            checkpoint = Path(snapshot_download(
                repo_id=config["base_model"], revision=config["base_revision"],
                local_files_only=False, etag_timeout=10, max_workers=4,
            )).resolve()
    if not (checkpoint / "rl_agent_config.json").is_file():
        raise ValueError(f"base checkpoint is not a local Laya checkpoint: {checkpoint}")
    return checkpoint


def _require_laya(device: str) -> Any:
    try:
        import torch
        import laya
    except ImportError as exc:
        raise RuntimeError("Laya backend needs the pinned optional dependency; install requirements-laya.txt") from exc
    if getattr(laya, "__version__", None) != "0.4.30":
        raise RuntimeError(f"Laya backend requires laya==0.4.30; found {getattr(laya, '__version__', 'unknown')}")
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested for Laya but torch.cuda.is_available() is false; no CPU fallback")
    return laya


def _runtime_record(device: str) -> dict[str, Any]:
    import torch

    result: dict[str, Any] = {
        "device": device,
        "torch_version": str(torch.__version__),
        "cuda_runtime_version": getattr(torch.version, "cuda", None),
    }
    if device == "cuda":
        result["gpu_name"] = torch.cuda.get_device_name(0)
        result["gpu_capability"] = list(torch.cuda.get_device_capability(0))
    return result


def train_laya_from_config(config: dict[str, Any], *, allow_model_download: bool = False) -> dict[str, Any]:
    dataset_summary = validate_laya_dataset_pair(config["train_file"], config["evaluation_file"])
    training = dict(config.get("training", {}))
    device = training.pop("device", "cuda")
    _require_laya(device)
    base_checkpoint = _resolve_base_checkpoint(config, allow_model_download=allow_model_download)
    output_dir = Path(config["output_dir"])
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"Laya checkpoint output is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    training["eval_data"] = str(config["evaluation_file"])
    try:
        from laya.train import TrainConfig, finetune
    except ImportError as exc:
        raise RuntimeError("installed Laya package lacks its fine-tuning API") from exc
    train_config = TrainConfig(**training)
    train_config.validate()
    report = finetune(
        data=str(config["train_file"]), model_dir=str(base_checkpoint),
        output_dir=str(output_dir), config=train_config, device=device,
    )
    if not (output_dir / "rl_agent_config.json").is_file() or not (output_dir / "model.safetensors").is_file():
        raise RuntimeError("Laya trainer returned without a loadable checkpoint")
    result = {
        "backend": "laya",
        "model": config["base_model"],
        "base_revision": config["base_revision"],
        "base_checkpoint": str(base_checkpoint),
        "checkpoint_dir": str(output_dir.resolve()),
        "runtime": _runtime_record(device),
        "training_settings": training,
        "train_sha256": _file_sha256(Path(config["train_file"])),
        "evaluation_sha256": _file_sha256(Path(config["evaluation_file"])),
        "dataset": dataset_summary,
        "training_report": json.loads(json.dumps(report, ensure_ascii=False, default=str)),
    }
    return result


def _load_evaluation_report(config: dict[str, Any], checkpoint: Path, *, device: str) -> dict[str, Any]:
    laya = _require_laya(device)
    try:
        from laya.evals import Dataset, evaluate
    except ImportError as exc:
        raise RuntimeError("installed Laya package lacks laya.evals") from exc
    dataset = Dataset.from_jsonl(str(config["evaluation_file"]))
    benchmark = config.get("benchmark", {})
    agent = laya.load(
        str(checkpoint), device=device, backend=benchmark.get("backend", "auto"),
    )
    actual_device = str(getattr(agent, "device", device))
    if device == "cuda" and not actual_device.lower().startswith("cuda"):
        raise RuntimeError(f"Laya requested CUDA but loaded on {actual_device}; refusing CPU benchmark")
    fallback_before = int(getattr(agent, "cpu_fallback_count", 0) or 0)
    report = evaluate(
        agent,
        dataset,
        batch_size=benchmark.get("batch_size", 1),
        sort_by_length=benchmark.get("sort_by_length", False),
        on_error="fail",
        config={
            "dataset_sha256": _file_sha256(Path(config["evaluation_file"])),
            "base_model": config["base_model"],
            "base_revision": config["base_revision"],
            "checkpoint_sha256": _directory_sha256(checkpoint),
            "training_data_sha256": _file_sha256(Path(config["train_file"])),
            "runtime": _runtime_record(device),
            "actual_device": actual_device,
            "actual_backend": str(getattr(agent, "_backend", benchmark.get("backend", "auto"))),
            "backend": benchmark.get("backend", "auto"),
        },
    )
    fallback_count = int(getattr(agent, "cpu_fallback_count", 0) or 0)
    if device == "cuda" and fallback_count > fallback_before:
        raise RuntimeError(f"Laya inference used CPU fallback {fallback_count - fallback_before} time(s); refusing a GPU benchmark")
    actual_device_after = str(getattr(agent, "device", actual_device))
    if device == "cuda" and not actual_device_after.lower().startswith("cuda"):
        raise RuntimeError(f"Laya benchmark ended on {actual_device_after}; refusing CPU results")
    serialized = report.to_json()
    return {"report": serialized, "overall": report.overall, "config": report.config}


def benchmark_laya_from_config(
    config: dict[str, Any],
    *,
    checkpoint_path: Path | str | None,
    output_path: Path | str,
    baseline_report_path: Path | str | None = None,
    allow_model_download: bool = False,
) -> dict[str, Any]:
    dataset_summary = validate_laya_dataset_pair(config["train_file"], config["evaluation_file"])
    benchmark = dict(config.get("benchmark", {}))
    device = benchmark.get("device", config.get("training", {}).get("device", "cuda"))
    _require_laya(device)
    base_checkpoint = _resolve_base_checkpoint(config, allow_model_download=allow_model_download)
    output = Path(output_path)
    if output.exists():
        raise ValueError(f"benchmark output already exists: {output}")
    if checkpoint_path is None:
        model_checkpoint = base_checkpoint
        candidate = False
    else:
        model_checkpoint = Path(checkpoint_path).resolve()
        if not (model_checkpoint / "rl_agent_config.json").is_file():
            raise ValueError(f"candidate is not a loadable Laya checkpoint: {model_checkpoint}")
        candidate = True
    baseline: dict[str, Any] | None = None
    evaluation_sha256 = _file_sha256(Path(config["evaluation_file"]))
    run_manifest_sha256 = _file_sha256(Path(config["_manifest_path"]))
    if candidate:
        if baseline_report_path is None:
            raise ValueError("paired Laya benchmark requires --baseline with the before report")
        try:
            baseline = json.loads(Path(baseline_report_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read Laya baseline report: {exc}") from exc
        if baseline.get("schema") != "local-ai-hub-laya-benchmark/1" or baseline.get("stage") != "baseline":
            raise ValueError("baseline is not a Local AI Hub Laya baseline report")
        if (baseline.get("run_manifest_sha256") != run_manifest_sha256
                or baseline.get("evaluation_sha256") != evaluation_sha256
                or baseline.get("base_model") != config["base_model"]
                or baseline.get("base_revision") != config["base_revision"]):
            raise ValueError("Laya baseline does not match the current manifest and evaluation dataset")
    measured = _load_evaluation_report(config, model_checkpoint, device=device)
    result: dict[str, Any] = {
        "schema": "local-ai-hub-laya-benchmark/1",
        "stage": "candidate" if candidate else "baseline",
        "run_manifest_sha256": run_manifest_sha256,
        "evaluation_sha256": evaluation_sha256,
        "base_model": config["base_model"],
        "base_revision": config["base_revision"],
        "model_checkpoint": str(model_checkpoint),
        "dataset": dataset_summary,
        "report": measured["report"],
    }
    if candidate:
        assert baseline is not None
        baseline_report = baseline.get("report", {})
        baseline_config = baseline_report.get("config", {})
        current_config = measured["config"]
        for identity in ("dataset_sha256", "questions_sha256", "laya_version"):
            if baseline_config.get(identity) != current_config.get(identity):
                raise ValueError(f"Laya before/after reports are incomparable: {identity} differs")
        before_metrics = baseline_report.get("overall", {})
        after_metrics = measured["overall"]
        common = sorted(set(before_metrics) & set(after_metrics))
        delta = {
            name: round(float(after_metrics[name]) - float(before_metrics[name]), 8)
            for name in common
            if isinstance(before_metrics[name], (int, float)) and not isinstance(before_metrics[name], bool)
            and isinstance(after_metrics[name], (int, float)) and not isinstance(after_metrics[name], bool)
        }
        result["summary"] = {"base": before_metrics, "candidate": after_metrics, "delta": delta}
    else:
        result["summary"] = {"base": measured["overall"]}
    _write_json_atomic(output, result)
    return result


def run_laya_matrix(matrix: dict[str, Any], *, allow_model_download: bool = False) -> list[dict[str, Any]]:
    dataset = validate_laya_dataset_pair(matrix["train_file"], matrix["evaluation_file"])
    output_root = Path(matrix["output_root"])
    run_dir = output_root / matrix["name"]
    run_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = run_dir / "checkpoint"
    run_manifest = run_dir / "run-manifest.json"
    effective = {
        "schema_version": 1,
        "name": matrix["name"],
        "backend": "laya",
        "task_type": "decision_model",
        "base_model": matrix["base_model"],
        "base_revision": matrix["base_revision"],
        "train_file": matrix["train_file"],
        "evaluation_file": matrix["evaluation_file"],
        "output_dir": str(checkpoint_dir.resolve()),
        "training": matrix.get("training", {}),
        "benchmark": matrix.get("benchmark", {}),
    }
    if run_manifest.exists():
        existing = json.loads(run_manifest.read_text(encoding="utf-8"))
        if existing != effective:
            raise ValueError(f"Laya run manifest changed; use a fresh output directory: {run_dir}")
    else:
        _write_json_atomic(run_manifest, effective)
    effective = load_laya_run_manifest(run_manifest)
    run_hash = _file_sha256(run_manifest)
    eval_hash = _file_sha256(Path(effective["evaluation_file"]))
    train_hash = _file_sha256(Path(effective["train_file"]))
    before_path = run_dir / "benchmark-before.json"
    if before_path.exists():
        before = json.loads(before_path.read_text(encoding="utf-8"))
        base_checkpoint = _resolve_base_checkpoint(effective, allow_model_download=allow_model_download)
        current_base_sha = _directory_sha256(base_checkpoint)
        if (before.get("schema") != "local-ai-hub-laya-benchmark/1" or before.get("stage") != "baseline"
                or before.get("run_manifest_sha256") != run_hash or before.get("evaluation_sha256") != eval_hash
                or before.get("base_model") != effective["base_model"]
                or before.get("base_revision") != effective["base_revision"]
                or before.get("report", {}).get("config", {}).get("checkpoint_sha256") != current_base_sha):
            raise ValueError(f"stale Laya baseline does not match current manifest/data: {before_path}")
    else:
        before = benchmark_laya_from_config(
            effective, checkpoint_path=None, output_path=before_path,
            allow_model_download=allow_model_download,
        )
    training_record_path = run_dir / "training-run.json"
    if training_record_path.exists():
        training_record = json.loads(training_record_path.read_text(encoding="utf-8"))
        if (training_record.get("run_manifest_sha256") != run_hash
                or training_record.get("evaluation_sha256") != eval_hash
                or training_record.get("train_sha256") != train_hash
                or training_record.get("base_model") != effective["base_model"]
                or not (checkpoint_dir / "rl_agent_config.json").is_file()
                or training_record.get("checkpoint_sha256") != _directory_sha256(checkpoint_dir)):
            raise ValueError(f"Laya training record does not match current manifest/data: {training_record_path}")
    else:
        if checkpoint_dir.exists() and any(checkpoint_dir.iterdir()):
            raise ValueError(f"partial Laya checkpoint exists without training record: {checkpoint_dir}")
        training_record = train_laya_from_config(effective, allow_model_download=allow_model_download)
        training_record.update({
            "run_manifest_sha256": run_hash,
            "evaluation_sha256": eval_hash,
            "train_sha256": train_hash,
            "base_model": effective["base_model"],
            "checkpoint_sha256": _directory_sha256(checkpoint_dir),
        })
        _write_json_atomic(training_record_path, training_record)
    after_path = run_dir / "benchmark-after.json"
    if after_path.exists():
        after = json.loads(after_path.read_text(encoding="utf-8"))
        if (after.get("schema") != "local-ai-hub-laya-benchmark/1" or after.get("stage") != "candidate"
                or after.get("run_manifest_sha256") != run_hash or after.get("evaluation_sha256") != eval_hash
                or after.get("base_model") != effective["base_model"]
                or after.get("base_revision") != effective["base_revision"]
                or after.get("report", {}).get("config", {}).get("checkpoint_sha256")
                != training_record.get("checkpoint_sha256")):
            raise ValueError(f"stale Laya candidate report does not match current manifest/data: {after_path}")
    else:
        after = benchmark_laya_from_config(
            effective, checkpoint_path=checkpoint_dir, output_path=after_path,
            baseline_report_path=before_path, allow_model_download=allow_model_download,
        )
    result = {
        "model": matrix["name"],
        "base_model": effective["base_model"],
        "base_revision": effective["base_revision"],
        "run_dir": str(run_dir.resolve()),
        "dataset": dataset,
        "before": before["summary"]["base"],
        "after": after["summary"],
        "training": training_record,
    }
    return [result]
