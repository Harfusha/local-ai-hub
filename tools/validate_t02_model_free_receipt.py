"""Validate T02's model-free baseline manifest and external per-case records."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> int:
    manifest_path = ROOT / "handoff" / "T02-cross-task-dataset-manifest.json"
    receipt_path = ROOT / "handoff" / "T02-model-free-baseline-receipt-2026-10-01.json"
    plugin_path = ROOT / "tools" / "t02_lifecycle_pytest_plugin.py"
    manifest = _read_json(manifest_path)
    receipt = _read_json(receipt_path)
    manifest_receipt = manifest.get("model_free_per_case_validation")
    if not isinstance(manifest_receipt, dict) or manifest_receipt.get("receipt_sha256") != _sha256(receipt_path):
        raise ValueError("manifest receipt digest does not match receipt file")

    if manifest.get("schema_version") != "t02-cross-task-dataset-manifest/v1":
        raise ValueError("unexpected T02 dataset manifest schema")
    datasets = manifest.get("datasets")
    if not isinstance(datasets, list) or [item.get("task") for item in datasets] != ["T10", "T11", "T15"]:
        raise ValueError("expected T10/T11/T15 dataset definitions")
    matrix = manifest.get("t02_required_matrix")
    if not isinstance(matrix, dict):
        raise ValueError("missing T02 required matrix")
    expected_cases = len(matrix["repository_file_counts"]) * len(matrix["rag_chunk_counts"])
    if expected_cases != 6 or matrix.get("required_case_count") != expected_cases:
        raise ValueError("T02 matrix must define six cases")

    coverage = receipt.get("coverage")
    cases = receipt.get("measured_model_free_cases")
    if not isinstance(coverage, dict) or not isinstance(cases, list):
        raise ValueError("missing measured model-free case evidence")
    if coverage.get("t02_required_cases") != 6 or coverage.get("measured_per_case") != len(cases):
        raise ValueError("model-free coverage counts do not match receipt")
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("invalid measured case row")
        record_path = Path(str(case["record_path"]))
        record = _read_json(record_path)
        if _sha256(record_path) != case["record_sha256"]:
            raise ValueError(f"record digest mismatch: {record_path}")
        metadata = record.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError(f"missing record metadata: {record_path}")
        if metadata.get("baseline_readiness") != "per_case":
            raise ValueError(f"unexpected readiness: {record_path}")
        if metadata.get("inference") != "skipped_not_requested":
            raise ValueError(f"model inference was not skipped: {record_path}")
        if metadata.get("synthetic_file_count") != case.get("repository_files"):
            raise ValueError(f"file-count mismatch: {record_path}")
        if metadata.get("rag_chunk_count") != case.get("rag_chunks"):
            raise ValueError(f"RAG-count mismatch: {record_path}")
        if record.get("failed_stages") != []:
            raise ValueError(f"record has failed stages: {record_path}")

    plugin_source = plugin_path.read_text(encoding="utf-8")
    ast.parse(plugin_source, filename=str(plugin_path))
    if 'print("T02_LIFECYCLE "' not in plugin_source or "file=sys.stderr" not in plugin_source:
        raise ValueError("lifecycle diagnostics must write to stderr")
    plugin_receipt = receipt.get("lifecycle_plugin_validation")
    if not isinstance(plugin_receipt, dict) or plugin_receipt.get("plugin_sha256") != _sha256(plugin_path):
        raise ValueError("lifecycle plugin digest does not match receipt")

    print(
        "PASS: manifest=3 cross-task datasets; T02_cases=6; "
        f"model_free_records={len(cases)}; lifecycle_plugin=stderr; "
        f"receipt_sha256={_sha256(receipt_path)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
