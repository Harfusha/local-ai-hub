from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .benchmark import benchmark_from_manifest
from .manifest import validate_dataset_pair, validate_run_options
from .train import train_from_manifest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_matching_artifact(path: Path, *, run_hash: str, evaluation_hash: str, base_model: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("run_manifest_sha256") != run_hash or value.get("evaluation_sha256") != evaluation_hash:
        raise ValueError(f"stale artifact does not match current manifest/data: {path}")
    if value.get("base_model") != base_model:
        raise ValueError(f"artifact uses a different base model: {path}")
    return value


def load_matrix_manifest(path: Path | str) -> dict[str, Any]:
    manifest_path = Path(path).resolve()
    try:
        config = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read matrix manifest: {exc}") from exc
    if not isinstance(config, dict):
        raise ValueError("matrix manifest must be a JSON object")
    required = ("schema_version", "name", "task_type", "train_file", "evaluation_file", "output_root", "output_schema", "models")
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"matrix manifest missing fields: {', '.join(missing)}")
    if config["schema_version"] != 1 or not isinstance(config["task_type"], str) or config["task_type"] not in {"preprocess_card", "decision_model"}:
        raise ValueError("unsupported matrix manifest schema_version or task_type")
    if not isinstance(config["name"], str) or not config["name"].strip():
        raise ValueError("matrix name must be non-empty")
    if not isinstance(config["output_schema"], dict):
        raise ValueError("output_schema must be a JSON Schema object")
    try:
        Draft202012Validator.check_schema(config["output_schema"])
    except Exception as exc:
        raise ValueError(f"output_schema is invalid: {exc}") from exc
    models = config["models"]
    if not isinstance(models, list) or not models:
        raise ValueError("matrix needs a non-empty models list")
    if not isinstance(config.get("training", {}), dict) or not isinstance(config.get("benchmark", {}), dict) or not isinstance(config.get("lora", {}), dict):
        raise ValueError("matrix training, benchmark, and lora options must be objects")
    names: set[str] = set()
    for item in models:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not isinstance(item.get("base_model"), str):
            raise ValueError("each model needs name and base_model strings")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", item["name"]):
            raise ValueError(f"unsafe model run name: {item['name']}")
        if not item["base_model"].strip() or item["name"] in names:
            raise ValueError("model names must be unique and base_model non-empty")
        names.add(item["name"])
        training = dict(config.get("training", {}))
        training.update(item.get("training", {}))
        benchmark = config.get("benchmark", {})
        lora = dict(config.get("lora", {}))
        lora.update(item.get("lora", {}))
        validate_run_options(training, benchmark, lora)
    for key in ("train_file", "evaluation_file", "output_root"):
        value = Path(config[key])
        config[key] = str(value if value.is_absolute() else (manifest_path.parent / value).resolve())
    config["_manifest_path"] = str(manifest_path)
    return config


def run_matrix(manifest_path: Path | str, *, allow_model_download: bool = False) -> list[dict[str, Any]]:
    matrix = load_matrix_manifest(manifest_path)
    dataset = validate_dataset_pair(matrix["train_file"], matrix["evaluation_file"])
    output_root = Path(matrix["output_root"])
    results: list[dict[str, Any]] = []
    for model_spec in matrix["models"]:
        run_dir = output_root / model_spec["name"]
        run_dir.mkdir(parents=True, exist_ok=True)
        adapter_dir = run_dir / "adapter"
        run_manifest = run_dir / "run-manifest.json"
        training = dict(matrix.get("training", {}))
        training.update(model_spec.get("training", {}))
        lora = dict(matrix.get("lora", {}))
        lora.update(model_spec.get("lora", {}))
        effective = {
            "schema_version": 1,
            "name": f"{matrix['name']}-{model_spec['name']}",
            "task_type": matrix["task_type"],
            "base_model": model_spec["base_model"],
            "revision": model_spec.get("revision"),
            "train_file": matrix["train_file"],
            "evaluation_file": matrix["evaluation_file"],
            "output_dir": str(adapter_dir.resolve()),
            "system_prompt": matrix.get("system_prompt", "Task prompt is stored in each dataset row."),
            "output_schema": matrix["output_schema"],
            "training": training,
            "benchmark": matrix.get("benchmark", {}),
            "lora": lora,
        }
        if run_manifest.exists():
            existing = json.loads(run_manifest.read_text(encoding="utf-8"))
            if existing != effective:
                raise ValueError(f"run manifest changed; use a fresh output directory: {run_dir}")
        else:
            run_manifest.write_text(json.dumps(effective, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        run_hash = _sha256(run_manifest)
        eval_hash = _sha256(Path(matrix["evaluation_file"]))
        train_hash = _sha256(Path(matrix["train_file"]))

        before_path = run_dir / "benchmark-before.json"
        if before_path.exists():
            before = _load_matching_artifact(before_path, run_hash=run_hash, evaluation_hash=eval_hash, base_model=model_spec["base_model"])
        else:
            before = benchmark_from_manifest(
                run_manifest, adapter_path=None, output_path=before_path,
                allow_model_download=allow_model_download,
            )
        training_record_path = adapter_dir / "training_run.json"
        if training_record_path.exists():
            training_record = _load_matching_artifact(training_record_path, run_hash=run_hash, evaluation_hash=eval_hash, base_model=model_spec["base_model"])
            if training_record.get("train_sha256") != train_hash:
                raise ValueError(f"training receipt does not match current training data: {training_record_path}")
        else:
            if adapter_dir.exists() and any(adapter_dir.iterdir()):
                raise ValueError(f"partial adapter output exists without training receipt: {adapter_dir}")
            training_record = train_from_manifest(run_manifest, allow_model_download=allow_model_download)
        after_path = run_dir / "benchmark-after.json"
        if after_path.exists():
            after = _load_matching_artifact(after_path, run_hash=run_hash, evaluation_hash=eval_hash, base_model=model_spec["base_model"])
        else:
            after = benchmark_from_manifest(
                run_manifest, adapter_path=adapter_dir, output_path=after_path,
                allow_model_download=allow_model_download,
            )
        result = {
            "model": model_spec["name"],
            "base_model": model_spec["base_model"],
            "run_dir": str(run_dir.resolve()),
            "dataset": dataset,
            "before": before["summary"]["base"],
            "after": after["summary"],
            "training": training_record,
        }
        results.append(result)
        print(json.dumps({"model": model_spec["name"], "phase": "complete", "run_dir": str(run_dir.resolve())}), flush=True)
    return results
