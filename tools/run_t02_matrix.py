"""Run the T02 synthetic workload matrix with verified per-case receipts.

This driver measures six documented file/RAG workloads across four concurrency
levels. It never enables inference; all generated records, scratch data, and
checkpoints live outside the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

FILE_COUNTS = (100, 10_000, 100_000)
RAG_CHUNK_COUNTS = (10_000, 100_000)
CONCURRENCY_LEVELS = (1, 4, 16, 32)
EXPECTED_CASES = tuple(
    (files, chunks)
    for files in FILE_COUNTS
    for chunks in RAG_CHUNK_COUNTS
)
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def expected_cells() -> list[tuple[int, int, int]]:
    """Return every required workload/concurrency cell in stable order."""
    return [(*case, level) for case in EXPECTED_CASES for level in CONCURRENCY_LEVELS]


def case_key(file_count: int, rag_chunk_count: int) -> str:
    return f"files-{file_count}-rag-{rag_chunk_count}"


def resolve_external_output(path: Path | str, repository_root: Path | str) -> Path:
    """Resolve a durable output path and reject anything inside the checkout."""
    root = Path(repository_root).expanduser().resolve()
    target = Path(path).expanduser().resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return target
    raise ValueError("evidence directory must be outside the repository")


def _valid_receipt(case: Any) -> bool:
    if not isinstance(case, dict) or case.get("status") != "complete":
        return False
    digest = case.get("record_sha256")
    return isinstance(digest, str) and _HEX_SHA256.fullmatch(digest) is not None


def pending_cases(manifest: dict[str, Any]) -> list[tuple[int, int]]:
    """Skip only matrix workloads carrying a completed record digest."""
    cases = manifest.get("cases", {})
    if not isinstance(cases, dict):
        cases = {}
    return [
        case for case in EXPECTED_CASES
        if not _valid_receipt(cases.get(case_key(*case)))
    ]


def build_command(
    *,
    python: str,
    repository_root: Path | str,
    output_dir: Path | str,
    file_count: int,
    rag_chunk_count: int,
    phase: str,
) -> list[str]:
    """Build one offline benchmark invocation with external durable paths."""
    if (file_count, rag_chunk_count) not in EXPECTED_CASES:
        raise ValueError("workload is outside the documented T02 matrix")
    if phase not in {"smoke", "acceptance"}:
        raise ValueError("phase must be smoke or acceptance")
    root = Path(repository_root).expanduser().resolve()
    output = resolve_external_output(output_dir, root)
    key = case_key(file_count, rag_chunk_count)
    repetitions = 3 if phase == "smoke" else 30
    light_repetitions = 10 if phase == "smoke" else 1_000
    comparison_repetitions = 3 if phase == "smoke" else 30
    command = [
        python, str(root / "tools" / "benchmark_surfaces.py"),
        "--state-dir", str(output / "state"),
        "--scratch-dir", str(output / "scratch" / key),
        "--files", str(file_count), "--rag-chunks", str(rag_chunk_count),
        "--repetitions", str(repetitions),
        "--light-repetitions", str(light_repetitions),
        "--comparison-repetitions", str(comparison_repetitions),
        "--concurrency", *(str(level) for level in CONCURRENCY_LEVELS),
        "--full",
    ]
    return command


def validate_case_record(
    record: dict[str, Any],
    file_count: int,
    rag_chunk_count: int,
    phase: str,
) -> list[str]:
    """Return contract failures for one benchmark JSON record."""
    errors: list[str] = []
    metadata = record.get("metadata") if isinstance(record, dict) else None
    if not isinstance(metadata, dict):
        return ["metadata_missing"]
    if record.get("success") is not True:
        errors.append("benchmark_not_successful")
    if metadata.get("synthetic_file_count") != file_count:
        errors.append("file_count_mismatch")
    if metadata.get("rag_chunk_count") != rag_chunk_count:
        errors.append("rag_chunk_count_mismatch")
    if metadata.get("concurrency") != list(CONCURRENCY_LEVELS):
        errors.append("concurrency_mismatch")
    repetitions = metadata.get("stage_repetitions")
    light = repetitions.get("light") if isinstance(repetitions, dict) else None
    paired = repetitions.get("paired") if isinstance(repetitions, dict) else None
    minimum_light, minimum_paired = (10, 3) if phase == "smoke" else (1_000, 30)
    if not isinstance(light, int) or isinstance(light, bool) or light < minimum_light:
        errors.append("light_repetitions_insufficient")
    if not isinstance(paired, int) or isinstance(paired, bool) or paired < minimum_paired:
        errors.append("paired_repetitions_insufficient")
    if metadata.get("inference") != "skipped_not_requested":
        errors.append("inference_was_not_skipped")
    stages = record.get("stages")
    queue = stages.get("hub_queue_admission") if isinstance(stages, dict) else None
    if not isinstance(queue, dict) or queue.get("status") != "passed":
        errors.append("queue_admission_stage_not_passed")
    by_level = queue.get("by_concurrency", {}) if isinstance(queue, dict) else {}
    if not isinstance(by_level, dict):
        by_level = {}
    for level in CONCURRENCY_LEVELS:
        sample = by_level.get(str(level))
        if not isinstance(sample, dict) or not isinstance(sample.get("count"), int):
            errors.append(f"concurrency_measurement_missing:{level}")
            continue
        if sample["count"] < level * minimum_light:
            errors.append(f"concurrency_sample_count_insufficient:{level}")
        if sample.get("error_count") != 0:
            errors.append(f"concurrency_errors_present:{level}")
    return errors


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_manifest(path: Path, *, resume: bool) -> dict[str, Any]:
    if not path.exists():
        if resume:
            raise ValueError("cannot resume: matrix manifest does not exist")
        return {"schema_version": 1, "phase": None, "cases": {}}
    if not resume:
        raise FileExistsError("matrix manifest exists; pass --resume")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or not isinstance(manifest.get("cases"), dict):
        raise ValueError("matrix manifest is invalid")
    return manifest


def _verified_completed_cases(
    manifest: dict[str, Any], *, output_dir: Path | str, phase: str
) -> set[tuple[int, int]]:
    completed: set[tuple[int, int]] = set()
    output = Path(output_dir).expanduser().resolve()
    cases = manifest.get("cases", {})
    for case in EXPECTED_CASES:
        item = cases.get(case_key(*case))
        if not _valid_receipt(item):
            continue
        record_path = item.get("record_path")
        if not isinstance(record_path, str):
            continue
        path = Path(record_path).expanduser().resolve()
        try:
            path.relative_to(output)
            payload = path.read_bytes()
        except (OSError, ValueError):
            continue
        if hashlib.sha256(payload).hexdigest() != item["record_sha256"]:
            continue
        try:
            record = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(record, dict) and not validate_case_record(record, *case, phase):
            completed.add(case)
    return completed


def _offline_environment(repository_root: Path | str) -> dict[str, str]:
    environment = os.environ.copy()
    source_root = str((Path(repository_root).expanduser().resolve() / "src"))
    inherited_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (source_root, inherited_pythonpath) if value
    )
    environment.update({
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
    })
    return environment


def _aggregate_matrix(
    manifest: dict[str, Any], *, output_dir: Path | str, phase: str
) -> dict[str, Any]:
    output = Path(output_dir).expanduser().resolve()
    completed: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    quality_records: list[dict[str, Any]] = []
    cases = manifest.get("cases", {})
    for file_count, rag_chunk_count in EXPECTED_CASES:
        item = cases[case_key(file_count, rag_chunk_count)]
        record_path = Path(item["record_path"]).expanduser().resolve()
        record_bytes = record_path.read_bytes()
        record = json.loads(record_bytes)
        digest = hashlib.sha256(record_bytes).hexdigest()
        if digest != item.get("record_sha256"):
            raise ValueError(f"matrix record changed after verification: {record_path}")
        if validate_case_record(record, file_count, rag_chunk_count, phase):
            raise ValueError(f"matrix record failed revalidation: {record_path}")
        completed.append({
            "file_count": file_count,
            "rag_chunk_count": rag_chunk_count,
            "record_path": str(record_path),
            "record_sha256": digest,
            "benchmark_exit_code": item.get("benchmark_exit_code"),
            "checkpoint_path": item.get("checkpoint_path"),
            "checkpoint_sha256": item.get("checkpoint_sha256"),
            "stage_repetitions": record["metadata"].get("stage_repetitions"),
        })
        stages = record.get("stages", {})
        queue = stages.get("hub_queue_admission", {})
        for level in CONCURRENCY_LEVELS:
            queue_level = queue.get("by_concurrency", {}).get(str(level), {})
            cells.append({
                "file_count": file_count,
                "rag_chunk_count": rag_chunk_count,
                "concurrency": level,
                "queue_admission": {
                    "status": queue.get("status"),
                    "count": queue_level.get("count"),
                    "p50_ms": queue_level.get("p50_ms"),
                    "p95_ms": queue_level.get("p95_ms"),
                    "throughput_per_second": queue_level.get("concurrent_admissions_per_second"),
                    "error_count": queue_level.get("error_count"),
                },
            })
        quality_records.append({
            "file_count": file_count,
            "rag_chunk_count": rag_chunk_count,
            "synthetic_quality": record.get("quality", {}),
            "synthetic_checks": record.get("synthetic_checks", {}),
            "golden_operations": record.get("golden", {}),
        })
    if len(cells) != len(expected_cells()):
        raise ValueError("matrix aggregation did not produce all 24 cells")
    aggregate = {
        "schema_version": 1,
        "phase": phase,
        "status": "complete_synthetic_matrix",
        "synthetic_only": True,
        "quality_acceptance": "blocked_real_input_evidence",
        "expected_cell_count": len(expected_cells()),
        "completed_cell_count": len(cells),
        "workload_count": len(completed),
        "workloads": completed,
        "cells": cells,
        "quality_records": quality_records,
        "limitation": "Synthetic benchmark quality is not real-input retrieval quality; model-backed operations remain unmeasured.",
    }
    aggregate_path = output / "t02-matrix-aggregate.json"
    _atomic_write(aggregate_path, aggregate)
    aggregate_bytes = aggregate_path.read_bytes()
    manifest["aggregate"] = {
        "status": aggregate["status"],
        "path": str(aggregate_path),
        "sha256": hashlib.sha256(aggregate_bytes).hexdigest(),
        "completed_cells": len(cells),
        "quality_acceptance": aggregate["quality_acceptance"],
    }
    return aggregate


def run_matrix(
    *,
    repository_root: Path | str,
    output_dir: Path | str,
    phase: str,
    python: str = sys.executable,
    resume: bool = False,
) -> dict[str, Any]:
    root = Path(repository_root).expanduser().resolve()
    output = resolve_external_output(output_dir, root)
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "t02-matrix-manifest.json"
    manifest = _load_manifest(manifest_path, resume=resume)
    if manifest.get("phase") not in {None, phase}:
        raise ValueError("matrix phase does not match existing manifest")
    manifest["phase"] = phase
    manifest["expected_cells"] = [list(cell) for cell in expected_cells()]
    manifest.setdefault("cases", {})
    _atomic_write(manifest_path, manifest)
    completed = _verified_completed_cases(manifest, output_dir=output, phase=phase)
    for file_count, rag_chunk_count in EXPECTED_CASES:
        case = (file_count, rag_chunk_count)
        if case in completed:
            continue
        key = case_key(*case)
        manifest["cases"][key] = {"status": "running", "file_count": file_count, "rag_chunk_count": rag_chunk_count}
        _atomic_write(manifest_path, manifest)
        checkpoint = output / "checkpoints" / f"{key}.json"
        command = build_command(
            python=python, repository_root=root, output_dir=output,
            file_count=file_count, rag_chunk_count=rag_chunk_count,
            phase=phase,
        )
        result = subprocess.run(
            command, cwd=root, capture_output=True, text=True, check=False,
            env=_offline_environment(root),
        )
        try:
            record = json.loads(result.stdout)
        except json.JSONDecodeError:
            record = None
        if not isinstance(record, dict):
            manifest["cases"][key] = {
                "status": "failed", "exit_code": result.returncode,
                "command": command,
                "checkpoint_path": str(checkpoint),
                "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest() if checkpoint.is_file() else None,
                "error": "benchmark_stdout_not_json", "stderr_tail": result.stderr[-2_000:],
            }
            _atomic_write(manifest_path, manifest)
            return {"success": False, "manifest_path": str(manifest_path), "cases": manifest["cases"]}
        errors = validate_case_record(record, file_count, rag_chunk_count, phase)
        record_path_value = record.get("record_path")
        record_path = Path(record_path_value) if isinstance(record_path_value, str) else None
        if record_path is None or not record_path.is_file():
            errors.append("record_file_missing")
        if result.returncode not in {0, 2}:
            errors.append(f"benchmark_exit_code:{result.returncode}")
        if errors:
            manifest["cases"][key] = {
                "status": "failed", "exit_code": result.returncode,
                "command": command,
                "checkpoint_path": str(checkpoint),
                "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest() if checkpoint.is_file() else None,
                "errors": errors, "record_path": str(record_path) if record_path else None,
            }
            _atomic_write(manifest_path, manifest)
            return {"success": False, "manifest_path": str(manifest_path), "cases": manifest["cases"]}
        digest = hashlib.sha256(record_path.read_bytes()).hexdigest()
        manifest["cases"][key] = {
            "status": "complete", "file_count": file_count,
            "rag_chunk_count": rag_chunk_count, "record_path": str(record_path),
            "record_sha256": digest, "benchmark_exit_code": result.returncode,
            "command": command,
            "checkpoint_path": str(checkpoint),
            "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest() if checkpoint.is_file() else None,
            "baseline_readiness": record["metadata"].get("baseline_readiness"),
            "baseline_readiness_reasons": record["metadata"].get("baseline_readiness_reasons", []),
        }
        _atomic_write(manifest_path, manifest)
        completed.add(case)
    aggregate = _aggregate_matrix(manifest, output_dir=output, phase=phase)
    _atomic_write(manifest_path, manifest)
    return {
        "success": len(completed) == len(EXPECTED_CASES),
        "phase": phase, "completed_workloads": len(completed),
        "completed_cells": len(completed) * len(CONCURRENCY_LEVELS),
        "expected_cells": len(expected_cells()), "manifest_path": str(manifest_path),
        "aggregate_path": str(output / "t02-matrix-aggregate.json"),
        "aggregate_sha256": hashlib.sha256((output / "t02-matrix-aggregate.json").read_bytes()).hexdigest(),
        "quality_acceptance": aggregate["quality_acceptance"],
        "cases": manifest["cases"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--phase", choices=("smoke", "acceptance"), default="smoke")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_matrix(
            repository_root=args.repository_root, output_dir=args.output_dir,
            phase=args.phase, python=args.python, resume=args.resume,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
