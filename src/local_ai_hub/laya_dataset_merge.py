"""Pool explicitly included Laya train rows from encrypted Hub diagnostic archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
    fields = {"id", "group_id", "source_sha256", "state", "questions", "expected", "provenance"}
    if not isinstance(row, dict) or set(row) != fields:
        raise ValueError("unexpected fields; expected candidate identity, group, provenance, state, questions, and expected")
    if not isinstance(row["id"], str) or not row["id"] or not isinstance(row["group_id"], str) or not row["group_id"]:
        raise ValueError("id and group_id must be non-empty strings")
    if not isinstance(row["source_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["source_sha256"]):
        raise ValueError("source_sha256 must be a lowercase SHA-256")
    if not isinstance(row["provenance"], dict) or row["provenance"].get("source") != "laya_candidate_store":
        raise ValueError("candidate provenance is missing or invalid")
    provenance = row["provenance"]
    if provenance.get("data_class") != "local_scoped":
        raise ValueError("candidate provenance.data_class must be local_scoped")
    if provenance.get("candidate_id") != row["id"]:
        raise ValueError("candidate provenance ID does not match row ID")
    if provenance.get("candidate_sha256") != row["source_sha256"]:
        raise ValueError("candidate provenance hash does not match source_sha256")
    if any(isinstance(key, str) and "consent" in key.casefold() for key in provenance):
        raise ValueError("retired consent provenance fields are not accepted")
    provenance_fields = {
        "source", "data_class", "candidate_id", "candidate_sha256",
        "repository_scope_sha256", "task_id", "session_id", "evidence_ids",
        "label_provenance",
    }
    if "label_provenance" not in provenance:
        raise ValueError("candidate provenance requires verified label provenance")
    for field in ("repository_scope_sha256", "task_id", "session_id", "evidence_ids"):
        if field not in provenance:
            raise ValueError(f"candidate provenance.{field} is required")
    if set(provenance) != provenance_fields:
        raise ValueError("candidate provenance fields are incomplete or unexpected")
    repository_scope_sha256 = provenance["repository_scope_sha256"]
    if (not isinstance(repository_scope_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", repository_scope_sha256)):
        raise ValueError("candidate provenance.repository_scope_sha256 must be a lowercase SHA-256")
    if any(not isinstance(provenance[field], str) or not provenance[field].strip()
           for field in ("task_id", "session_id")):
        raise ValueError("candidate provenance task_id and session_id must be non-empty strings")
    evidence_ids = provenance["evidence_ids"]
    if (not isinstance(evidence_ids, list) or not evidence_ids
            or any(not isinstance(item, str) or not item.strip() for item in evidence_ids)
            or len(set(evidence_ids)) != len(evidence_ids)):
        raise ValueError("candidate provenance.evidence_ids must contain unique non-empty IDs")
    label_provenance = provenance["label_provenance"]
    if not isinstance(label_provenance, dict):
        raise ValueError("candidate provenance requires verified label provenance")
    expected_label_fields = {
        "status", "method", "rubric_version", "target_sha256",
        "annotation_identity_sha256", "agreement", "adjudicator_identity_sha256",
        "verification_identity_sha256",
    }
    if set(label_provenance) != expected_label_fields:
        raise ValueError("label provenance fields are incomplete or unexpected")
    if label_provenance.get("status") != "verified":
        raise ValueError("label_provenance.status must be verified")
    if label_provenance.get("method") != "blind_double_annotation":
        raise ValueError("Laya training rows require blind double annotation")
    if not isinstance(label_provenance.get("rubric_version"), str) or not label_provenance["rubric_version"].strip():
        raise ValueError("label_provenance.rubric_version must be a non-empty string")
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
    target_sha256 = hashlib.sha256(_canonical_json(expected).encode("utf-8")).hexdigest()
    if label_provenance.get("target_sha256") != target_sha256:
        raise ValueError("label_provenance.target_sha256 does not match target labels")
    annotators = label_provenance.get("annotation_identity_sha256")
    if (not isinstance(annotators, list) or len(annotators) != 2
            or any(not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{64}", item) for item in annotators)
            or len(set(annotators)) != 2):
        raise ValueError("blind double annotation needs two distinct annotator identity hashes")
    if not isinstance(label_provenance.get("agreement"), bool):
        raise ValueError("label_provenance.agreement must be boolean")
    adjudicator = label_provenance.get("adjudicator_identity_sha256")
    if (not isinstance(adjudicator, str) or not re.fullmatch(r"[0-9a-f]{64}", adjudicator)
            or adjudicator in annotators):
        raise ValueError("label adjudicator must be independent of both annotators")
    verifier = label_provenance.get("verification_identity_sha256")
    if (not isinstance(verifier, str) or not re.fullmatch(r"[0-9a-f]{64}", verifier)
            or verifier in set(annotators) | {adjudicator}):
        raise ValueError("label verification reviewer must be independent")
    _canonical_json(row)


def merge_training_archives(sources: Sequence[tuple[str | Path, str]], output_dir: str | Path) -> dict[str, Any]:
    """Merge explicitly included AES-256 ZIP train members into a train-only JSONL directory.

    Rows preserve opaque candidate/group identities, but source archives contain
    train rows only and cannot supply a pooled held-out evaluation set.
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
            canonical = _canonical_json(row)
            input_key = _canonical_json({"state": row["state"], "questions": row["questions"]})
            label_key = _canonical_json(row["expected"])
            previous_label = labels_by_input.get(input_key)
            if previous_label is not None and previous_label != label_key:
                raise ValueError(f"{path}: conflicting labels for identical state/questions")
            labels_by_input[input_key] = label_key
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
        "schema_version": 2,
        "dataset_kind": "laya_train_only",
        "source_count": len(source_counts),
        "source_rows": source_counts,
        "input_rows": total_input_rows,
        "unique_rows": len(unique),
        "duplicate_rows_removed": duplicate_rows_removed,
        "train_jsonl_sha256": digest,
        "training_only": True,
        "evaluation_eligible": False,
        "evaluation_blocker": "source archives contain training rows only and no separate held-out evaluation data",
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
    parser = argparse.ArgumentParser(description="Merge locally scoped Laya train members from encrypted Hub ZIP exports.")
    parser.add_argument("archives", nargs="+", type=Path, help="AES-256 Hub ZIP archives containing scoped Laya train JSONL")
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
