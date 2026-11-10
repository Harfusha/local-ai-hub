"""Pool opted-in Laya train rows from encrypted Hub diagnostic archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Sequence

_MEMBER = "laya/candidates.train.jsonl"
_MAX_ARCHIVE_MEMBER_BYTES = 16 * 1024 * 1024
_MAX_TOTAL_OUTPUT_BYTES = 64 * 1024 * 1024
_MAX_ROWS = 100_000
_MAX_ARCHIVE_MEMBERS = 100_000
_MAX_SOURCES = 64


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _read_rows(archive_path: Path, password: str) -> list[dict[str, Any]]:
    try:
        import pyzipper
    except ImportError as exc:
        raise RuntimeError("pyzipper is required to read encrypted Hub ZIP exports") from exc
    if not isinstance(password, str) or not password:
        raise ValueError("each archive requires a non-empty password")
    try:
        with pyzipper.AESZipFile(archive_path, "r") as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_ARCHIVE_MEMBERS:
                raise ValueError(f"{archive_path}: archive member count exceeds limit")
            matches = [item for item in infos if item.filename == _MEMBER]
            if len(matches) != 1:
                raise ValueError(f"{archive_path}: expected exactly one {_MEMBER} member")
            info = matches[0]
            if info.wz_aes_strength != 3 or not (info.flag_bits & 0x1):
                raise ValueError(f"{archive_path}: train member must be AES-256 encrypted")
            if info.file_size > _MAX_ARCHIVE_MEMBER_BYTES:
                raise ValueError(f"{archive_path}: train member exceeds byte limit")
            archive.setpassword(password.encode("utf-8"))
            with archive.open(info, "r", pwd=password.encode("utf-8")) as member:
                payload = member.read(_MAX_ARCHIVE_MEMBER_BYTES + 1)
            if len(payload) > _MAX_ARCHIVE_MEMBER_BYTES:
                raise ValueError(f"{archive_path}: train member exceeds byte limit")
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith(str(archive_path)):
            raise
        raise ValueError(f"cannot read encrypted train member from {archive_path}: {exc}") from exc

    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(payload.splitlines(), start=1):
        try:
            row = json.loads(line)
            _validate_row(row)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError(f"{archive_path}: invalid train row at line {line_number}: {exc}") from exc
        rows.append(row)
        if len(rows) > _MAX_ROWS:
            raise ValueError(f"{archive_path}: train row count exceeds limit")
    if not rows:
        raise ValueError(f"{archive_path}: train member is empty")
    return rows


def _validate_row(row: Any) -> None:
    if not isinstance(row, dict) or set(row) != {"state", "questions", "expected"}:
        raise ValueError("unexpected fields; expected only state, questions, expected")
    if not isinstance(row["state"], str) or not isinstance(row["questions"], dict):
        raise ValueError("state must be text and questions must be an object")
    if not row["questions"] or any(not isinstance(key, str) or not isinstance(value, dict) for key, value in row["questions"].items()):
        raise ValueError("questions must map question IDs to objects")
    expected = row["expected"]
    if not isinstance(expected, dict) or len(expected) != 1:
        raise ValueError("expected must contain exactly one labeled question")
    question_id, label = next(iter(expected.items()))
    if not isinstance(question_id, str) or question_id not in row["questions"] or not isinstance(label, str):
        raise ValueError("expected must label a known question with a string")
    _canonical_json(row)


def merge_training_archives(sources: Sequence[tuple[str | Path, str]], output_dir: str | Path) -> dict[str, Any]:
    """Merge opted-in AES-256 ZIP train members into a train-only JSONL directory.

    The source exports omit global task/session/group provenance. The result is
    therefore never eligible for pooled calibration or evaluation.
    """
    if len(sources) < 2:
        raise ValueError("at least two training archives are required")
    if len(sources) > _MAX_SOURCES:
        raise ValueError("training archive count exceeds limit")
    output = Path(output_dir).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("output directory already exists")
    if not output.parent.is_dir():
        raise ValueError("output parent directory must already exist")

    unique: dict[str, dict[str, Any]] = {}
    labels_by_input: dict[str, str] = {}
    source_counts: list[dict[str, int]] = []
    duplicate_rows_removed = 0
    total_input_rows = 0
    total_input_bytes = 0

    for source_index, (source_path, password) in enumerate(sources, start=1):
        path = Path(source_path)
        if not path.is_file():
            raise ValueError(f"archive {source_index} does not exist or is not a file")
        rows = _read_rows(path, password)
        total_input_rows += len(rows)
        total_input_bytes += sum(len(_canonical_json(row).encode("utf-8")) + 1 for row in rows)
        if total_input_rows > _MAX_ROWS:
            raise ValueError("merged train input row count exceeds limit")
        if total_input_bytes > _MAX_TOTAL_OUTPUT_BYTES:
            raise ValueError("merged train input exceeds byte limit")
        added = 0
        for row in rows:
            input_key = _canonical_json({"state": row["state"], "questions": row["questions"]})
            label_key = _canonical_json(row["expected"])
            previous_label = labels_by_input.get(input_key)
            if previous_label is not None and previous_label != label_key:
                raise ValueError(f"{path}: conflicting labels for identical state/questions")
            labels_by_input[input_key] = label_key
            canonical = _canonical_json(row)
            if canonical in unique:
                duplicate_rows_removed += 1
                continue
            unique[canonical] = row
            added += 1
            if len(unique) > _MAX_ROWS:
                raise ValueError("merged train row count exceeds limit")
        source_counts.append({"source_index": source_index, "input_rows": len(rows), "new_unique_rows": added})

    if not unique:
        raise ValueError("no training rows found")
    payload = "".join(row + "\n" for row in unique).encode("utf-8")
    if len(payload) > _MAX_TOTAL_OUTPUT_BYTES:
        raise ValueError("merged train output exceeds byte limit")
    digest = hashlib.sha256(payload).hexdigest()
    manifest = {
        "schema_version": 1,
        "dataset_kind": "laya_train_only",
        "source_count": len(source_counts),
        "source_rows": source_counts,
        "input_rows": total_input_rows,
        "unique_rows": len(unique),
        "duplicate_rows_removed": duplicate_rows_removed,
        "train_jsonl_sha256": digest,
        "training_only": True,
        "evaluation_eligible": False,
        "evaluation_blocker": "source archives omit global task, session, group, and label provenance",
    }

    stage = Path(tempfile.mkdtemp(prefix=".laya-merge-", dir=output.parent))
    try:
        jsonl_path = stage / "laya.train.jsonl"
        with jsonl_path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        manifest_path = stage / "manifest.json"
        with manifest_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(_canonical_json(manifest) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(stage, output)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge opted-in Laya train members from encrypted Hub ZIP exports.")
    parser.add_argument("archives", nargs="+", type=Path, help="AES-256 Hub ZIP archives containing opted-in Laya train JSONL")
    parser.add_argument("--output-dir", required=True, type=Path, help="new directory for laya.train.jsonl and manifest.json")
    args = parser.parse_args(argv)
    if len(args.archives) < 2:
        parser.error("at least two encrypted training archives are required")

    from getpass import getpass

    sources = [(path, getpass(f"Password for archive {index} ({path.name}): ")) for index, path in enumerate(args.archives, start=1)]
    try:
        manifest = merge_training_archives(sources, args.output_dir)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Merged {manifest['input_rows']} rows into {manifest['unique_rows']} train rows.")
    print("Evaluation eligible: no. Global group provenance is absent from source exports.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
