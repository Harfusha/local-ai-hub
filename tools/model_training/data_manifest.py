"""Create privacy-bounded manifests for local model-training datasets."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_ROWS = 100_000
_MAX_BYTES = 512 * 1024 * 1024


def _is_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _confined_path(state_dir: Path, value: str | Path, *, must_exist: bool) -> Path:
    raw = Path(value)
    lexical = Path(os.path.abspath(raw if raw.is_absolute() else state_dir / raw))
    try:
        parts = lexical.relative_to(state_dir).parts
    except ValueError as exc:
        raise ValueError("dataset and manifest paths must remain inside state_dir") from exc
    current = state_dir
    for part in parts:
        current = current / part
        if current.exists() and _is_link(current):
            raise ValueError(f"symlink or junction is not allowed in dataset path: {current}")
    resolved = lexical.resolve(strict=must_exist)
    if resolved == state_dir or not resolved.is_relative_to(state_dir):
        raise ValueError("dataset and manifest paths must remain inside state_dir")
    if must_exist and not resolved.is_file():
        raise ValueError(f"dataset file is missing: {resolved}")
    return resolved


def _check_no_link_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.exists() and _is_link(current):
            raise ValueError(f"symlink or junction is not allowed in path: {current}")


def _read_rows(path: Path, *, dataset_name: str) -> tuple[list[dict[str, Any]], str]:
    if path.stat().st_size > _MAX_BYTES:
        raise ValueError(f"{dataset_name} dataset exceeds {_MAX_BYTES} bytes")
    rows: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for line_number, raw in enumerate(stream, 1):
            digest.update(raw)
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"{dataset_name} line {line_number} is not valid JSON") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{dataset_name} line {line_number} must be an object")
            if not isinstance(row.get("id"), str) or not row["id"]:
                raise ValueError(f"{dataset_name} line {line_number} needs a stable id")
            if not isinstance(row.get("group_id"), str) or not row["group_id"]:
                raise ValueError(f"{dataset_name} line {line_number} needs a group_id")
            if not isinstance(row.get("provenance"), dict):
                raise ValueError(f"{dataset_name} line {line_number} needs provenance")
            if len(rows) >= _MAX_ROWS:
                raise ValueError(f"{dataset_name} exceeds {_MAX_ROWS} rows")
            rows.append(row)
    return rows, digest.hexdigest()


def _unique_hashes(rows: list[dict[str, Any]], field: str, *, nested: bool = False) -> set[str]:
    values: set[str] = set()
    for row in rows:
        value: Any = row.get("provenance", {}).get(field) if nested else row.get(field)
        if isinstance(value, str) and _SHA256.fullmatch(value):
            values.add(value)
    return values


def _section(path: Path, state_dir: Path, rows: list[dict[str, Any]], digest: str) -> dict[str, Any]:
    return {
        "path": path.relative_to(state_dir).as_posix(),
        "sha256": digest,
        "row_count": len(rows),
        "group_count": len({row["group_id"] for row in rows}),
        "unique_id_count": len({row["id"] for row in rows}),
    }


def create_manifest(
    *,
    state_dir: str | Path,
    dataset_format: str,
    train_path: str | Path,
    output_path: str | Path,
    evaluation_path: str | Path | None = None,
    source_path: str | Path | None = None,
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    raw_state = Path(state_dir)
    state_lexical = Path(os.path.abspath(raw_state))
    _check_no_link_components(state_lexical)
    state = state_lexical.resolve(strict=True)
    if not state.is_dir():
        raise ValueError("state_dir must be an existing directory")
    if dataset_format not in {"card-training", "embedding-corpus", "laya"}:
        raise ValueError("format must be card-training, embedding-corpus, or laya")
    if dataset_format == "laya" and (not isinstance(snapshot_id, str) or not snapshot_id.strip()):
        raise ValueError("Laya manifests require the verified snapshot_id")
    if dataset_format != "laya" and snapshot_id is not None:
        raise ValueError("snapshot_id is only valid for Laya datasets")

    train = _confined_path(state, train_path, must_exist=True)
    output = _confined_path(state, output_path, must_exist=False)
    if output.exists():
        raise ValueError(f"manifest already exists: {output}")
    if train == output:
        raise ValueError("manifest path must differ from dataset path")
    train_rows, train_digest = _read_rows(train, dataset_name="train")
    if not train_rows:
        raise ValueError("train dataset is empty")

    evaluation: Path | None = None
    eval_rows: list[dict[str, Any]] = []
    eval_digest: str | None = None
    if evaluation_path is not None:
        evaluation = _confined_path(state, evaluation_path, must_exist=True)
        if evaluation in {train, output}:
            raise ValueError("train, evaluation, and manifest paths must be distinct")
        eval_rows, eval_digest = _read_rows(evaluation, dataset_name="evaluation")
        if not eval_rows:
            raise ValueError("evaluation dataset is empty")
    elif dataset_format != "laya":
        raise ValueError("non-Laya manifests require an evaluation dataset")

    train_ids = {row["id"] for row in train_rows}
    eval_ids = {row["id"] for row in eval_rows}
    if len(train_ids) != len(train_rows) or len(eval_ids) != len(eval_rows):
        raise ValueError("dataset contains duplicate row IDs")
    if train_ids & eval_ids:
        raise ValueError("train/evaluation ID leakage detected")
    train_groups = {row["group_id"] for row in train_rows}
    eval_groups = {row["group_id"] for row in eval_rows}
    if train_groups & eval_groups:
        raise ValueError("train/evaluation project or group leakage detected")

    train_hashes: set[str] = set()
    eval_hashes: set[str] = set()
    if dataset_format == "card-training":
        train_hashes = _unique_hashes(train_rows, "source_sha256")
        eval_hashes = _unique_hashes(eval_rows, "source_sha256")
        if any(not isinstance(row.get("source_sha256"), str)
               or not _SHA256.fullmatch(row["source_sha256"])
               for row in train_rows + eval_rows):
            raise ValueError("card-training rows need valid source_sha256 values")
    elif dataset_format == "embedding-corpus":
        train_hashes = _unique_hashes(train_rows, "card_sha256", nested=True)
        eval_hashes = _unique_hashes(eval_rows, "card_sha256", nested=True)
        if len(train_hashes) != len(train_rows) or len(eval_hashes) != len(eval_rows):
            raise ValueError("embedding rows need valid provenance.card_sha256 values")
    if train_hashes & eval_hashes:
        raise ValueError("train/evaluation content-hash leakage detected")

    source_section = None
    if source_path is not None:
        source = _confined_path(state, source_path, must_exist=True)
        if source in {train, evaluation, output}:
            raise ValueError("source, train, evaluation, and manifest paths must be distinct")
        source_rows, source_digest = _read_rows(source, dataset_name="source")
        source_section = _section(source, state, source_rows, source_digest)
    else:
        source_rows = []

    hash_field = "source_sha256" if dataset_format == "card-training" else (
        "provenance.card_sha256" if dataset_format == "embedding-corpus" else None
    )
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "dataset_format": dataset_format,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": source_section,
        "train": _section(train, state, train_rows, train_digest),
        "evaluation": _section(evaluation, state, eval_rows, eval_digest) if evaluation else None,
        "source_to_split": {
            "source_row_count": len(source_rows),
            "train_evaluation_row_count": len(train_rows) + len(eval_rows),
            "rows_removed_before_split": max(0, len(source_rows) - len(train_rows) - len(eval_rows)),
        } if source_path is not None else None,
        "split_integrity": {
            "id_overlap_count": 0,
            "group_overlap_count": 0,
            "content_hash_overlap_count": 0 if hash_field else None,
            "content_hash_field": hash_field,
        },
        "labels_present": dataset_format != "embedding-corpus",
        "evaluation_status": "unassessed" if dataset_format == "laya" else "dataset_only",
    }
    if dataset_format == "laya":
        manifest["snapshot_id"] = snapshot_id
        manifest["train_only"] = True
        manifest["labels_verified_by_exporter"] = False
    manifest_text = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(manifest_text)
            stream.flush()
            os.fsync(stream.fileno())
        if output.exists() or _is_link(output):
            raise ValueError(f"manifest path appeared during write: {output}")
        Path(temporary_name).replace(output)
    finally:
        Path(temporary_name).unlink(missing_ok=True)
    return {"success": True, "manifest_path": str(output), "manifest": manifest}


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a project-confined dataset manifest")
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--format", required=True, choices=("card-training", "embedding-corpus", "laya"))
    parser.add_argument("--train", required=True, type=Path)
    parser.add_argument("--evaluation", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--snapshot-id")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = create_manifest(
        state_dir=args.state_dir,
        dataset_format=args.format,
        train_path=args.train,
        evaluation_path=args.evaluation,
        source_path=args.source,
        snapshot_id=args.snapshot_id,
        output_path=args.output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
